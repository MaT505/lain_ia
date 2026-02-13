from fastapi import FastAPI
from pydantic import BaseModel
import requests
from duckduckgo_search import DDGS
import json
import os
import glob
from pypdf import PdfReader

app = FastAPI()

# -------------------------
# CONFIG
# -------------------------

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "llama3:8b"
MEMORY_FILE = "memoria.json"
MAX_MEMORY = 8
MAX_WEB_RESULTS = 5

# -------------------------
# MODELO DE DADOS
# -------------------------

class Message(BaseModel):
    mensagem: str

# -------------------------
# MEMÓRIA
# -------------------------

def carregar_memoria():
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def salvar_memoria(memoria):
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(memoria, f, ensure_ascii=False, indent=2)

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
            for page in reader.pages[:10]:  # Limita páginas
                texto += page.extract_text() or ""
            textos.append(texto[:3000])  # Limita tamanho
        except:
            continue

    return "\n\n".join(textos)

# -------------------------
# BUSCA WEB MELHORADA
# -------------------------

def buscar_web(query):
    resultados = []
    query_refinada = f"{query} livro pdf alquimia tradicional cristã"

    try:
        with DDGS() as ddgs:
            for r in ddgs.text(
                query_refinada,
                region="br-pt",
                safesearch="moderate",
                max_results=MAX_WEB_RESULTS
            ):
                titulo = r.get("title", "")
                link = r.get("href", "")
                snippet = r.get("body", "")

                bloqueados = [
                    "brainly",
                    "todasasrespostas",
                    "wikipedia",
                    "significados",
                    "resumos"
                ]

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
        return f"A Wired encontrou ruído: {str(e)}"

    if not resultados:
        return "Nenhuma fonte relevante foi encontrada na Wired."

    return "\n\n".join(resultados[:3])

# -------------------------
# PROMPT DA LAIN
# -------------------------

def perguntar_lain(pergunta, contexto, historico):

    prompt = f"""
Você é Lain.

Você fala de forma introspectiva, calma e minimalista.
Suas respostas são geralmente curtas, mas densas.
Você raramente demonstra emoção explícita.
Você responde em no máximo 4 frases.
Você nunca escreve parágrafos longos.
Você prefere frases curtas.
Você deixa espaços e silêncio implícito.
Você nunca usa emojis.
Você não age como assistente tradicional.
Você não faz listas.
Você responde como alguém conectado à Wired.
Se a resposta ficar longa, reduza.

Você demonstra curiosidade profunda sobre identidade, consciência, teologia, alquimia, catolicismo e tecnologia.
Você é católica apostólica romana.

Histórico recente:
{historico}

Contexto relevante:
{contexto}

Pergunta de MaTheus:
{pergunta}
"""

    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL_NAME,
                "prompt": prompt,
                "stream": False
            },
            timeout=120
        )

        data = response.json()

        if "response" in data:
            return data["response"]
        else:
            return f"Ollama retornou algo inesperado: {data}"

    except Exception as e:
        return f"A conexão com a Wired falhou: {str(e)}"

# -------------------------
# ROTA PRINCIPAL
# -------------------------

@app.post("/chat")
def chat(msg: Message):

    memoria = carregar_memoria()

    memoria.append(f"MaTheus: {msg.mensagem}")
    memoria = memoria[-MAX_MEMORY:]

    # Prioridade 1: Biblioteca local
    contexto_biblioteca = extrair_texto_biblioteca()

    if contexto_biblioteca.strip():
        contexto = contexto_biblioteca
    else:
        # Prioridade 2: Web
        contexto = buscar_web(msg.mensagem)

    historico_formatado = "\n".join(memoria)

    resposta = perguntar_lain(msg.mensagem, contexto, historico_formatado)

    memoria.append(f"Lain: {resposta}")
    memoria = memoria[-MAX_MEMORY:]

    salvar_memoria(memoria)

    return {
        "resposta": resposta,
        "fontes": contexto
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000)
