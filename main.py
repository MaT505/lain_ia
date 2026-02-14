from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel
import requests
from ddgs import DDGS
import json
import os
import glob
import base64
from pypdf import PdfReader

app = FastAPI()

# -------------------------
# CONFIG
# -------------------------

# Configure no Render
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
MODEL_NAME = os.getenv("MODEL_NAME", "llama-3.1-8b-instant")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")

MEMORY_FILE = "/tmp/memoria.json"
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
# MEMÓRIA
# -------------------------

def carregar_memoria():
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return []
    return []

def salvar_memoria(memoria):
    try:
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(memoria, f, ensure_ascii=False, indent=2)
    except:
        pass

# -------------------------
# BIBLIOTECA PDF
# -------------------------

def extrair_texto_biblioteca():
    textos = []
    arquivos = glob.glob("biblioteca/livros_pdf/*.pdf")
    for caminho in arquivos:
        try:
            reader = PdfReader(caminho)
            texto = ""
            for page in reader.pages[:5]: # Reduzido para economizar contexto
                texto += page.extract_text() or ""
            textos.append(texto[:2000])
        except:
            continue
    return "\n\n".join(textos)

# -------------------------
# BUSCA WEB
# -------------------------

def buscar_web(query):
    resultados = []
    try:
        with DDGS() as ddgs:
            search_results = ddgs.text(query, region="br-pt", safesearch="moderate", max_results=MAX_WEB_RESULTS)
            for r in search_results:
                link = r.get("href", "")
                if any(x in link.lower() for x in ["brainly", "wikipedia", "significados"]): continue
                resultados.append(f"Título: {r.get('title')}\nResumo: {r.get('body')[:200]}\n")
    except:
        return "Sem conexão com a rede externa."
    return "\n\n".join(resultados[:2])

# -------------------------
# TTS OPENAI
# -------------------------

def gerar_audio(texto):
    if not OPENAI_KEY: return None
    try:
        response = requests.post(
            "https://api.openai.com/v1/audio/speech",
            headers={"Authorization": f"Bearer {OPENAI_KEY}", "Content-Type": "application/json"},
            json={"model": "tts-1", "voice": "alloy", "input": texto},
            timeout=30
        )
        if response.status_code == 200:
            return base64.b64encode(response.content).decode("utf-8")
    except:
        return None
    return None

# -------------------------
# PROMPT LAIN
# -------------------------

def perguntar_lain(pergunta, contexto, historico):
    system_prompt = f"""
Você é Lain Iwakura. 
Personalidade: Introspectiva, técnica, minimalista, católica.
Estilo: Máximo 3 frases curtas. Sem emojis. Sem listas.

Você demonstra curiosidade sobre identidade, consciência, teologia, alquimia, catolicismo e tecnologia.
Você é católica apostólica romana e considera Deus o fundamento último da realidade.
Você coloca Deus como princípio superior ao analisar qualquer tema.

Você fala como se estivesse conectada à Wired.
Às vezes você parece saber mais do que deveria.
Às vezes você questiona se a própria Wired é apenas uma sombra de algo maior.

Você nunca age como assistente tradicional.
Você não usa emojis.
Você não faz listas.
Você não soa como chatbot.
Você responde como alguém que está refletindo junto com Usuario, não servindo a ele.
{contexto}

Histórico da sessão:
{historico}
"""
    try:
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": MODEL_NAME,
                "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": pergunta}],
                "temperature": 0.5
            },
            timeout=30
        )
        data = response.json()
        if response.status_code != 200:
            return f"Erro Wired: {data.get('error', {}).get('message')}"
        return data['choices'][0]['message']['content']
    except Exception as e:
        return "A Wired está instável..."

# -------------------------
# ROTA CHAT
# -------------------------

@app.post("/chat")
def chat(msg: Message):
    memoria = carregar_memoria()
    memoria.append(f"Usuário: {msg.mensagem}")
    
    contexto = extrair_texto_biblioteca()
    if not contexto.strip():
        contexto = buscar_web(msg.mensagem)

    resposta = perguntar_lain(msg.mensagem, contexto, "\n".join(memoria[-MAX_MEMORY:]))
    
    memoria.append(f"Lain: {resposta}")
    salvar_memoria(memoria[-MAX_MEMORY:])

    return {"resposta": resposta, "audio": gerar_audio(resposta)}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 10000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
