import argparse
import os
import shutil
import concurrent.futures
import pandas as pd
from langchain.prompts import ChatPromptTemplate
from langchain_community.llms.ollama import Ollama
from langchain_community.document_loaders import PyPDFDirectoryLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain.schema.document import Document
from langchain_community.vectorstores import Chroma
from pyngrok import ngrok
from flask import Flask, request, jsonify, Response, stream_with_context, send_from_directory, render_template_string, session
import ollama
from flask_socketio import SocketIO, emit

sessions = {}
CHROMA_PATH = r"C:\Users\luzo.neto\OneDrive - Sicoob\Meus Arquivos"
DATA_PATH = r"C:\Users\luzo.neto\OneDrive - Sicoob\Documentos\Regulamento CNV"
EXCEL_PATH = r"C:\Users\luzo.neto\OneDrive - Sicoob\Meus Arquivos\historico_perguntas_respostas.xlsx"

PROMPT_TEMPLATE = """
Responda à pergunta como se fosse um gerente senior de uma cooperativa de crédito de forma clara e respeitosa, com base apenas no seguinte contexto:

{context}

---

Responda à pergunta como se fosse um gerente senior de uma cooperativa de crédito de forma clara e respeitosa, com base no contexto acima: {question}
"""

from langchain_community.embeddings.ollama import OllamaEmbeddings

def get_embedding_function():
    embeddings = OllamaEmbeddings(model='nomic-embed-text:latest', show_progress=True)
    return embeddings

def load_documents():
    document_loader = PyPDFDirectoryLoader(DATA_PATH)
    return document_loader.load()

def split_documents(documents: list[Document]):
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1200,
        chunk_overlap=120,
        length_function=len,
        is_separator_regex=False,
    )
    return text_splitter.split_documents(documents)

def add_to_chroma(chunks: list[Document]):
    db = Chroma(
        persist_directory=CHROMA_PATH, embedding_function=get_embedding_function()
    )

    chunks_with_ids = calculate_chunk_ids(chunks)
    existing_items = db.get(include=[])
    existing_ids = set(existing_items["ids"])
    print(f"Numeros de páginas no DB: {len(existing_ids)}")

    new_chunks = []
    for chunk in chunks_with_ids:
        if chunk.metadata["id"] not in existing_ids:
            new_chunks.append(chunk)

    if len(new_chunks):
        print(f"Adicionandos: {len(new_chunks)} Documentos")
        new_chunk_ids = [chunk.metadata["id"] for chunk in new_chunks]
        db.add_documents(new_chunks, ids=new_chunk_ids)
        db.persist()
    else:
        print("Nada para Atualizar")

def calculate_chunk_ids(chunks):
    last_page_id = None
    current_chunk_index = 0

    for chunk in chunks:
        source = chunk.metadata.get("source")
        page = chunk.metadata.get("page")
        current_page_id = f"{source}:{page}"

        if current_page_id == last_page_id:
            current_chunk_index += 1
        else:
            current_chunk_index = 0

        chunk_id = f"{current_page_id}:{current_chunk_index}"
        last_page_id = current_page_id

        chunk.metadata["id"] = chunk_id

    return chunks

def process_documents(documents):
    chunks = split_documents(documents)
    add_to_chroma(chunks)

def main():
    documents = load_documents()
    chunk_limit = 165
    
    while documents:
        chunk_batch = documents[:chunk_limit]
        documents = documents[chunk_limit:]
        
        with concurrent.futures.ThreadPoolExecutor() as executor:
            executor.submit(process_documents, chunk_batch)

def save_to_excel(question: str, answer: str):
    if os.path.exists(EXCEL_PATH):
        df = pd.read_excel(EXCEL_PATH)
    else:
        df = pd.DataFrame(columns=["Pergunta", "Resposta"])

    new_entry = pd.DataFrame({"Pergunta": [question], "Resposta": [answer]})
    df = pd.concat([df, new_entry], ignore_index=True)
    df.to_excel(EXCEL_PATH, index=False)
    
def init_ollama_session():
    if 'ollama_instance' not in session:
        session['ollama_instance'] = {
            'model': 'llama3.1',
            'messages': []
        }
    return session['ollama_instance']

def get_response_from_model(user_content: str, sid: str):
    
    embedding_function = get_embedding_function()
    db = Chroma(persist_directory=CHROMA_PATH, embedding_function=embedding_function)

    results = db.similarity_search_with_score(user_content, k=3)
    context_text = "\n\n".join([doc.page_content for doc, _score in results])
    prompt_template = ChatPromptTemplate.from_template(PROMPT_TEMPLATE)
    prompt = prompt_template.format(context=context_text, question=user_content)

    # Recupera ou inicializa a sessão do Ollama para o usuário
    ollama_instance = sessions.get(sid, {'model': 'llama3.1', 'messages': []})
    ollama_instance['messages'].append({'role': 'user', 'content': prompt})

    response_text = ""
    stream = ollama.chat(
        model=ollama_instance['model'],
        messages=ollama_instance['messages'],
        stream=True,
    )
    for chunk in stream:
        response_chunk = chunk['message']['content']
        socketio.emit('response_chunk', {'data': response_chunk}, room=sid)
        response_text += response_chunk

    # Atualiza a sessão com a última resposta
    ollama_instance['messages'].append({'role': 'assistant', 'content': response_text})

    # Atualiza a sessão global
    sessions[sid] = ollama_instance

    formatted_response = f"Response: {response_text}\nSources: {[doc.metadata.get('id', None) for doc, _score in results]}"

    # Salvar a resposta completa após o término do streaming
    save_to_excel(user_content, response_text)
    socketio.emit('response_complete', room=sid)
    return formatted_response
    

app = Flask(__name__)
app.secret_key = os.urandom(24)
socketio = SocketIO(app)


@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/query', methods=['POST'])
def handle_query():
    data = request.json
    question = data.get('question')
    sid = request.sid
    if not question:
        return jsonify({"error": "Pergunta não fornecida"}), 400

    response = get_response_from_model(question, sid)
    print(f"Pergunta: {question}")
    print(f"Resposta: {response}")
    return jsonify({'response': response})

@socketio.on('connect')
def handle_connect():
    sid = request.sid
    sessions[sid] = {
        'model': 'llama3.1',
        'messages': []
    }
    print(f"Conexão estabelecida: {sid}")

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    if sid in sessions:
        del sessions[sid]
    print(f"Conexão encerrada: {sid}")

@socketio.on('send_message')
def handle_message(data):
    content = data.get('content')
    sid = request.sid
    if not content:
        return

    emit("response_chunk", {'data':'Só um momento, estou verificando...'}, room=sid)

    print(f"Recebido: {content} - Conexão: {sid}")
    response = get_response_from_model(content, sid)
    #emit('response_chunk', {'data': response}, room=sid)
    
if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, allow_unsafe_werkzeug=True)
