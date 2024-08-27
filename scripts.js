document.addEventListener('DOMContentLoaded', () => {
    // Gerar um UUID para identificar a sessão da guia
    function generateUUID() {
        return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
            var r = Math.random() * 16 | 0, v = c == 'x' ? r : (r & 0x3 | 0x8);
            return v.toString(16);
        });
    }

    var sessionId = localStorage.getItem('sessionId');
    if (!sessionId) {
        sessionId = generateUUID();
        localStorage.setItem('sessionId', sessionId);
    }

    var socket = io.connect('http://' + document.domain + ':' + location.port, {
        query: "sessionId=" + sessionId
    });

    var form = document.getElementById('chatForm');
    var responseDiv = document.getElementById('response');
    var currentResponseMessage;
    var currentSources;

    form.addEventListener('submit', (event) => {
        event.preventDefault();
        var content = document.getElementById('content').value;

        // Adicionar a mensagem do usuário ao chat
        var userMessage = document.createElement('div');
        userMessage.textContent = content;
        userMessage.classList.add('user-message');
        responseDiv.appendChild(userMessage);
        responseDiv.scrollTop = responseDiv.scrollHeight;

        // Enviar a mensagem ao servidor
        socket.emit('send_message', {'content': content});
        document.getElementById('content').value = '';
        currentResponseMessage = null;  // Reset current response message
    });

    socket.on('response_chunk', (data) => {
        if (!currentResponseMessage) {
            currentResponseMessage = document.createElement('div');
            currentResponseMessage.classList.add('response-message');
        }
        if (data.data.startsWith("Response:")) {
            // Separar a resposta das fontes
            const responseParts = data.data.split("Sources:");
            currentResponseMessage.innerHTML += responseParts[0];

            // Salvar as fontes para uso no popup
            currentSources = responseParts[1].trim();

            // Adicionar botão de fontes
            var sourceButton = document.createElement('button');
            sourceButton.textContent = "Ver Fontes";
            sourceButton.classList.add('source-button');
            sourceButton.onclick = function() {
                var modal = document.getElementById("sourceModal");
                var span = document.getElementsByClassName("close")[0];
                document.getElementById("sourceContent").textContent = currentSources;

                // Mostrar o modal
                modal.style.display = "block";

                // Fechar o modal ao clicar no X
                span.onclick = function() {
                    modal.style.display = "none";
                }

                // Fechar o modal ao clicar fora dele
                window.onclick = function(event) {
                    if (event.target == modal) {
                        modal.style.display = "none";
                    }
                }
            };
            currentResponseMessage.appendChild(sourceButton);
        } else {
            currentResponseMessage.innerHTML += data.data;
        }

        responseDiv.appendChild(currentResponseMessage);
        responseDiv.scrollTop = responseDiv.scrollHeight;
    });
});
