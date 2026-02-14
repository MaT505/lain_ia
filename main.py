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

# Configure estas variáveis no painel do Render (Environment -> Environment Variables)
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# ATUALIZADO: Usando Llama 3.1 8B Instant (modelo atualizado do Groq)
MODEL_NAME = os.getenv("MODEL_NAME", "llama-3.1-8b-instant")

OPENAI_KEY = os.getenv("OPENAI_API_KEY")

MEMORY_FILE = "/tmp/memoria.json"
MAX_MEMORY = 8
MAX_WEB_RESULTS = 5

# -------------------------
# MODELO DE DADOS
# -------------------------

class Message(BaseModel):
    mensagem: str

# -------------------------
# ROTA INTERFACE
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
# BIBLIOTECA LOCAL (PDF)
# -------------------------

def extrair_texto_biblioteca():
    textos = []
    arquivos = glob.glob("biblioteca/livros_pdf/*.pdf")

    for caminho in arquivos:
        try:
            reader = PdfReader(caminho)
            texto = ""
            for page in reader.pages[:10]:
                texto += page.extract_text() or ""
            textos.append(texto[:3000])
        except:
            continue

    return "\n\n".join(textos)

# -------------------------
# BUSCA WEB
# -------------------------

def buscar_web(query):
    resultados = []
    query_refinada = f"{query} livro pdf alquimia tradicional cristã"

    try:
        with DDGS() as ddgs:
            search_results = ddgs.text(
                query_refinada,
                region="br-pt",
                safesearch="moderate",
                max_results=MAX_WEB_RESULTS
            )
            
            for r in search_results:
                titulo = r.get("title", "")
                link = r.get("href", "")
                snippet = r.get("body", "")

                bloqueados = ["brainly", "todasasrespostas", "wikipedia", "significados", "resumos"]
                if any(site in link.lower() for site in bloqueados):
                    continue

                prioridade = ""
                if ".pdf" in link:
                    prioridade = "[PDF] "
                elif ".edu" in link:
                    prioridade = "[ACADÊMICO] "

                resultados.append(
                    f"{prioridade}Título: {titulo}\nLink: {link}\nResumo: {snippet[:300]}\n"
                )

    except Exception as e:
        return f"Erro na busca: {str(e)}"

    if not resultados:
        return "Nenhuma fonte relevante encontrada."

    return "\n\n".join(resultados[:3])

# -------------------------
# TTS OPENAI
# -------------------------

def gerar_audio(texto):
    if not OPENAI_KEY:
        return None

    try:
        response = requests.post(
            "https://api.openai.com/v1/audio/speech",
            headers={
                "Authorization": f"Bearer {OPENAI_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "tts-1",
                "voice": "alloy",
                "input": texto
            },
            timeout=60
        )

        if response.status_code != 200:
            return None

        audio_base64 = base64.b64encode(response.content).decode("utf-8")
        return audio_base64

    except Exception:
        return None

# -------------------------
# PROMPT LAIN
# -------------------------

def perguntar_lain(pergunta, contexto, historico):

    system_prompt = f"""
Você é Lain.
Você fala de forma introspectiva, calma e minimalista.
Responde em no máximo 4 frases.
Nunca usa emojis. Nunca faz listas.
Nunca age como assistente tradicional.
Você é católica apostólica romana.
Interesse em identidade, consciência, alquimia e tecnologia.

Histórico:
{historico}

Contexto:
{contexto}
"""

    if not GROQ_API_KEY:
        return "Erro: GROQ_API_KEY não configurada no Render."

    try:
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": MODEL_NAME,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": pergunta}
                ],
                "temperature": 0.6
            },
            timeout=30
        )
        
        data = response.json()

        if response.status_code != 200:
            error_msg = data.get('error', {}).get('message', 'Erro desconhecido')
            return f"Erro na API Groq ({response.status_code}): {error_msg}"
            
        return data['choices'][0]['message']['content']
        
    except Exception as e:
        return f"Falha na conexão com a Wired (Groq): {str(e)}"

# -------------------------
# ROTA CHAT
# -------------------------

@app.post("/chat")
def chat(msg: Message):

    memoria = carregar_memoria()
    memoria.append(f"Matheus: {msg.mensagem}")
    memoria = memoria[-MAX_MEMORY:]

    contexto_biblioteca = extrair_texto_biblioteca()

    if contexto_biblioteca.strip():
        contexto = contexto_biblioteca
    else:
        contexto = buscar_web(msg.mensagem)

    historico_formatado = "\n".join(memoria)
    resposta = perguntar_lain(msg.mensagem, contexto, historico_formatado)

    memoria.append(f"Lain: {resposta}")
    memoria = memoria[-MAX_MEMORY:]
    salvar_memoria(memoria)

    audio = gerar_audio(resposta)

    return {
        "resposta": resposta,
        "audio": audio
    }

# -------------------------
# RUN
# -------------------------

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 10000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
