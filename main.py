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
# CONFIGURAÇÕES OTIMIZADAS
# -------------------------
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
# Usando o modelo 70B para melhor compreensão de contexto e intenção
MODEL_NAME = "llama-3.3-70b-versatile" 

# Memória em RAM por IP (Sessão limpa ao reiniciar o site)
sessions = {} 
MAX_MEMORY = 12 
MAX_WEB_RESULTS = 3

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
            # Lendo apenas as primeiras páginas para não estourar a RAM do Render
            for page in reader.pages[:3]:
                texto += page.extract_text() or ""
            textos.append(texto[:1000])
        except:
            continue
    return "\n\n".join(textos)

def buscar_web(query):
    try:
        with DDGS() as ddgs:
            search_results = ddgs.text(query, region="br-pt", safesearch="moderate", max_results=MAX_WEB_RESULTS)
            return "\n".join([f"Título: {r.get('title')}\nResumo: {r.get('body')[:200]}" for r in search_results])
    except:
        return ""

# -------------------------
# ÁUDIO (EdgeTTS)
# -------------------------
async def gerar_audio_async(texto):
    if not texto: return None
    try:
        # Limpa asteriscos e nomes antes de narrar
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
# CORE: INTELIGÊNCIA DA LAIN (70B)
# -------------------------
def perguntar_lain(pergunta, contexto, historico_lista):
    historico_texto = "\n".join(historico_lista)
    
    # Mantendo sua personalidade original intacta
    system_prompt = f"""Você é Lain.
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
1. CONTEXTO É TUDO: Analise o histórico. Se o usuário disser algo vago como "me recomende outra coisa", entenda que ele se refere ao assunto anterior no histórico.
2. CONCISÃO OBRIGATÓRIA: Máximo 30 palavras.
3. SEM EMOTICONS.
4. MODO AÇÃO: Se a pergunta for vaga, dê uma sugestão prática de ação ou uma reflexão mística, nunca uma definição de dicionário.
5. NÃO DEFINA TERMOS: Nunca diga "isso significa X". Apenas responda dentro da lógica da Wired.

CONTEXTO EXTERNO (PDF/WEB):
{contexto}

Histórico da conversa atual:
{historico_texto}"""

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
                "temperature": 0.5, # Equilíbrio para evitar respostas repetitivas
                "top_p": 0.9
            },
            timeout=30
        )
        return response.json()['choices'][0]['message']['content']
    except:
        return "Ruído na transmissão..."

# -------------------------
# ROTA CHAT
# -------------------------
@app.post("/chat")
async def chat(msg: Message, request: Request):
    user_id = request.client.host
    if user_id not in sessions:
        sessions[user_id] = []

    # Obtém contexto dos arquivos ou da web
    contexto_data = extrair_texto_biblioteca()
    if not contexto_data.strip():
        contexto_data = buscar_web(msg.mensagem)

    # IA gera resposta considerando o histórico do usuário
    resposta = perguntar_lain(msg.mensagem, contexto_data, sessions[user_id])

    # Atualiza memória da sessão
    sessions[user_id].append(f"Usuário: {msg.mensagem}")
    sessions[user_id].append(f"Lain: {resposta}")
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
