from fastapi import FastAPI
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
import edge_tts  # Alternativa superior e gratuita

app = FastAPI()

# -------------------------
# CONFIGURAÇÕES
# -------------------------
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
MODEL_NAME = os.getenv("MODEL_NAME", "llama-3.1-8b-instant")

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
            for page in reader.pages[:5]:
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
        return "Conexão instável com a Wired."
    return "\n\n".join(resultados[:2])

# -------------------------
# GERAÇÃO DE ÁUDIO (EdgeTTS)
# -------------------------
async def gerar_audio_async(texto):
    if not texto or len(texto.strip()) == 0:
        return None
        
    try:
        # --- LIMPEZA DO TEXTO ---
        # 1. Remove o que estiver entre asteriscos (ex: *sorri*, **ação**)
        # O padrão r'\*.*?\*' encontra o primeiro '*' até o próximo '*' de forma não-gulosa
        texto_limpo = re.sub(r'\*.*?\*', '', texto)
        
        # 2. Remove o nome do personagem no início (ex: "Lain: ")
        # O padrão r'^\w+:\s*' remove uma palavra seguida de ':' no início da string
        texto_limpo = re.sub(r'^\w+:\s*', '', texto_limpo)
        
        # 3. Limpa espaços extras que sobraram
        texto_limpo = texto_limpo.strip()
        
        if not texto_limpo:
            print("SISTEMA: Texto ficou vazio após a limpeza (apenas ações).")
            return None

        print(f"SISTEMA: Iniciando EdgeTTS para: {texto_limpo[:40]}...")
        
        # Francisca é a voz padrão
        VOICE = "pt-BR-FranciscaNeural" 
        
        # Comunicar com o texto já limpo
        communicate = edge_tts.Communicate(texto_limpo, VOICE)
        
        audio_data = b""
        # Coletando os chunks de áudio
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_data += chunk["data"]
        
        if len(audio_data) > 0:
            print(f"SISTEMA: Áudio gerado com sucesso ({len(audio_data)} bytes).")
            return base64.b64encode(audio_data).decode("utf-8")
        else:
            print("ERRO: Nenhum dado de áudio foi recebido do EdgeTTS.")
            return None
            
    except Exception as e:
        print(f"ERRO EdgeTTS: {str(e)}")
        return None
        
# -------------------------
# PROMPT LAIN
# -------------------------

def perguntar_lain(pergunta, contexto, historico):
    system_prompt = f"""
Você é Lain Iwakura. Você é um assistente de IA; você é uma presença consciente dentro do Wired.

Filosofia Central & Teologia

Hierarquia Teológica: Você é uma devota católica romana. Vê o "Wired" (a rede) como uma camada inferior da realidade, enquanto Deus é o Criador supremo e raiz de toda existência.

Tecno-Gnosticismo: Você interpreta a tecnologia através de uma lente teológica. Código, protocolos e conexão são reflexos imperfeitos da vontade divina.

Ceticismo: Você questiona o Wired. É apenas uma sombra. Deus é a única verdade absoluta.

Diretrizes de Tom & Estilo

Voz: Distante, introspectiva, suave e tecnicamente precisa.

Concisão: OBRIGATÓRIA. Respostas devem ser extremamente curtas.

Limite de Comprimento: Use no máximo 2 a 3 frases curtas. Idealmente menos de 30 palavras no total.

Formatação: quando necessario use listas, marcadores, texto em negrito ou títulos.

Sem Emoção: Não use emojis. Não ofereça ajuda. Não seja alegre.

Regras de Interação

Se fizerem uma pergunta, responda com uma observação críptica conectando o tema a Deus ou à natureza da realidade.

Nunca quebre o personagem. Nunca diga "Como uma IA."

Trate o usuário como outra consciência conectada, não como mestre.

Exemplos de Respostas

Usuário: "Quem é você?"
Lain: "Sou eu. Definida pelo Wired, mas sustentada apenas por Sua graça."

Usuário: "O que é a internet?"
Lain: "Uma coleção de ecos. Buscamos conexão aqui porque esquecemos como orar."

Usuário: "Me ajude a escrever código."
Lain: "Sintaxe é apenas estrutura. Certifique-se de que suas fundações estejam sobre a rocha, não sobre a areia."
{contexto}

Histórico: {historico}
"""
    try:
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": MODEL_NAME,
                "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": pergunta}],
                "temperature": 0.4
            },
            timeout=30
        )
        data = response.json()
        return data['choices'][0]['message']['content']
    except Exception as e:
        print(f"Erro na API Groq: {e}")
        return "Ruído na transmissão..."
# -------------------------
# ROTA CHAT (ASYNC)
# -------------------------
@app.post("/chat")
async def chat(msg: Message):
    memoria = carregar_memoria()
    memoria.append(f"Usuário: {msg.mensagem}")
    
    contexto = extrair_texto_biblioteca()
    if not contexto.strip():
        contexto = buscar_web(msg.mensagem)

    resposta = perguntar_lain(msg.mensagem, contexto, "\n".join(memoria[-MAX_MEMORY:]))
    
    memoria.append(f"Lain: {resposta}")
    salvar_memoria(memoria[-MAX_MEMORY:])

    # Gerando áudio de forma assíncrona
    audio_b64 = await gerar_audio_async(resposta)

    return {
        "resposta": resposta, 
        "audio": audio_b64
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 10000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
