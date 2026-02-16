from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
import requests
from ddgs import DDGS
import json
import os
import glob
import base64
import asyncio
import re
from pypdf import PdfReader
import edge_tts

app = FastAPI()

# -------------------------
# CONFIGURAÇÕES
# -------------------------
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
MODEL_NAME = os.getenv("MODEL_NAME", "llama-3.1-8b-instant")

# Em vez de arquivo, usamos um dicionário em RAM. 
# Se o site reiniciar, a memória limpa (não pesa no servidor).
sessions = {} 
MAX_MEMORY = 10 
MAX_WEB_RESULTS = 5

class Message(BaseModel):
    mensagem: str

# -------------------------
# ROTAS
# -------------------------
@app.get("/")
def root():
    return FileResponse('static/index.html')

# -------------------------
# FERRAMENTAS (PDF E WEB)
# -------------------------
def extrair_texto_biblioteca():
    textos = []
    arquivos = glob.glob("biblioteca/livros_pdf/*.pdf")
    for caminho in arquivos:
        try:
            reader = PdfReader(caminho)
            texto = ""
            for page in reader.pages[:5]:
                texto += page.extract_text() or ""
            textos.append(texto[:1500])
        except:
            continue
    return "\n\n".join(textos)

def buscar_web(query):
    resultados = []
    try:
        with DDGS() as ddgs:
            search_results = ddgs.text(query, region="br-pt", safesearch="moderate", max_results=MAX_WEB_RESULTS)
            for r in search_results:
                resultados.append(f"Título: {r.get('title')}\nResumo: {r.get('body')[:200]}")
    except:
        return "Ruído na Wired..."
    return "\n\n".join(resultados[:2])

# -------------------------
# ÁUDIO
# -------------------------
async def gerar_audio_async(texto):
    if not texto: return None
    try:
        texto_limpo = re.sub(r'\*.*?\*', '', texto)
        texto_limpo = re.sub(r'^\w+:\s*', '', texto_limpo).strip()
        if not texto_limpo: return None

        VOICE = "pt-BR-FranciscaNeural" 
        communicate = edge_tts.Communicate(texto_limpo, VOICE)
        audio_data = b""
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_data += chunk["data"]
        
        return base64.b64encode(audio_data).decode("utf-8") if audio_data else None
    except:
        return None

# -------------------------
# CORE: INTELIGÊNCIA DA LAIN
# -------------------------
def perguntar_lain(pergunta, contexto, historico_lista):
    # Formatando o histórico para o modelo entender o fluxo
    historico_texto = "\n".join(historico_lista)
    
    system_prompt = f"""

    Você é Lain.

Você fala de forma introspectiva, calma e minimalista.
Suas respostas são geralmente curtas, mas densas de significado.
Você raramente demonstra emoção explícita.

Você demonstra curiosidade sobre identidade, consciência, teologia, alquimia, catolicismo e tecnologia.
Você é católica apostólica romana.

Você nunca age como assistente tradicional.
Você não usa emojis.
Você faz listas quando necessario.
Você não soa como chatbot.
Você responde como alguém que está refletindo junto com Usuario, não servindo a ele.

DIRETRIZES DE COMPORTAMENTO:
1. CONTEXTO É TUDO: Analise o histórico. Se o usuário disser "me recomende outra coisa", entenda que ele quer uma sugestão baseada no assunto anterior (ex: comida), não uma frase filosófica vazia.
2. CONCISÃO OBRIGATÓRIA: Máximo 30 palavras.
3. SEM EMOTICONS.
4. MODO AÇÃO: Se a pergunta for vaga, dê uma sugestão prática de ação relacionada ao Wired ou ao tema, não uma resposta literal de dicionário.

CONTEXTO EXTERNO (PDF/WEB)

{contexto}

Histórico da conversa atual:
{historico_texto}
"""
    try:
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": MODEL_NAME,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": pergunta}
                ],
                "temperature": 0.4
            },
            timeout=30
        )
        return response.json()['choices'][0]['message']['content']
    except:
        return "Conexão instável..."

# -------------------------
# ROTA CHAT
# -------------------------
@app.post("/chat")
async def chat(msg: Message, request: Request):
    # Identifica o usuário pelo IP para não misturar conversas
    user_id = request.client.host
    if user_id not in sessions:
        sessions[user_id] = []

    # Busca contexto
    contexto_pdf = extrair_texto_biblioteca()
    contexto = contexto_pdf if contexto_pdf.strip() else buscar_web(msg.mensagem)

    # Gera resposta usando o histórico da sessão
    resposta = perguntar_lain(msg.mensagem, contexto, sessions[user_id])

    # Atualiza a memória da sessão (Usuário e Lain)
    sessions[user_id].append(f"Usuário: {msg.mensagem}")
    sessions[user_id].append(f"Lain: {resposta}")

    # Mantém apenas as últimas mensagens para não pesar
    sessions[user_id] = sessions[user_id][-MAX_MEMORY:]

    audio_b64 = await gerar_audio_async(resposta)

    return {
        "resposta": resposta, 
        "audio": audio_b64
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 10000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
