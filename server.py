#!/usr/bin/env python3
"""Chiquinho Sorvetes Teresópolis - atendente virtual demo.
Python stdlib only. Retrieval sobre cardápio completo (792 itens).
Run: python3 server.py  (porta 8788)

IA: deepseek-v4-flash-free via OpenCode Zen (rápido).
Chave: env OPENCODE_API_KEY ou arquivo .env no projeto.
Sem chave → fallback Ollama local (qwen3:4b).
"""
import json
import os
import re
import unicodedata
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

OPENCODE_URL = "https://opencode.ai/zen/v1/chat/completions"
OPENCODE_MODEL = "deepseek-v4-flash-free"
OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
OLLAMA_MODEL = "qwen3:4b"
# Cloud Run injeta a variável PORT (padrão 8080); localmente usa 8788.
PORT = int(os.environ.get("PORT", "8788"))

INDEX = json.loads((Path(__file__).parent / "menu_index.json").read_text("utf-8"))


def load_api_key():
    """Lê OPENCODE_API_KEY do ambiente ou do .env do projeto."""
    key = os.environ.get("OPENCODE_API_KEY", "").strip()
    if key:
        return key
    env_file = Path(__file__).parent / ".env"
    if env_file.exists():
        for line in env_file.read_text("utf-8").splitlines():
            line = line.strip()
            if line.startswith("OPENCODE_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


API_KEY = load_api_key()

STOPWORDS = {
    "o", "a", "os", "as", "um", "uma", "de", "do", "da", "dos", "das", "em",
    "no", "na", "nos", "nas", "para", "pra", "qual", "quais", "quanto", "custa",
    "custa", "custa", "preco", "preço", "tem", "têm", "vocês", "voce", "me",
    "eu", "quero", "gostaria", "por", "favor", "oi", "ola", "olá", "bom",
    "dia", "tarde", "noite", "aqui", "loja", "chiquinho", "sorvetes",
}

HIGHLIGHT_GROUPS = ["Casquinha", "Açaí", "Milk Shake 300ml", "Bubble Waffle", "Chiquinho no Pote", "Cafeteria"]

HOURS_RE = re.compile(
    r"(abre|abrem|aberto|aberta|fecha|fecham|fechado|hor[áa]rio|funciona|funcionam|at[eé] que horas|que horas|hora)",
    re.I,
)

ADDRESS_RE = re.compile(
    r"(endere[çc]o|localiza[çãa]o|onde fica|onde voc[êe]s ficam|mapa|rua|avenida|av\.|bairro)",
    re.I,
)

# Pedido genérico de cardápio (ex.: botão "Cardápio da loja" da página inicial).
MENU_RE = re.compile(
    r"(card[áa]pio|menu|quero ver|o que tem|o que voc[êe]s tem|quais sabores|lista de|pre[çc]os|op[çc][õo]es)",
    re.I,
)

GROUP_NAMES = sorted({i["grupo"] for i in INDEX}, key=len, reverse=True)


def _flat(s):
    return unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode()


def has_group_name(text):
    t = _flat(text.lower())
    return any(_flat(g.lower()) in t for g in GROUP_NAMES)


def build_menu_summary():
    groups = {}
    skip = {"Adicional", "EMBALAGEM"}
    for i in INDEX:
        if not i["disp"] or i["grupo"] in skip:
            continue
        groups.setdefault(i["grupo"], []).append(i["pdv"])
    order = [g for g in HIGHLIGHT_GROUPS if g in groups]
    order += [g for g in sorted(groups, key=lambda x: -len(groups[x])) if g not in order]
    labels = {
        "Milk Shake 300ml": "Milk Shake 300ml",
        "Milk Shake 400ml": "Milk Shake 400ml",
        "Milk Shake 500ml": "Milk Shake 500ml",
        "Açai": "Açaí",
        "Cascao": "Cascão",
        "Agua Mineral": "Bebidas",
    }
    pretty = [labels.get(g, g) for g in order]
    cheap = min((p for ps in groups.values() for p in ps))
    return (
        "Claro! 😋 Nosso cardápio tem: " + ", ".join(pretty) + ". "
        f"Preços a partir de R$ {cheap:.2f}. "
        "Me diz qual linha ou sabor te interessa que eu te passo os preços! 😊"
    )


MENU_SUMMARY = build_menu_summary()


def build_highlights():
    parts = []
    for g in HIGHLIGHT_GROUPS:
        cands = [i for i in INDEX if i["disp"] and g.lower() in i["grupo"].lower()]
        if not cands:
            continue
        best = min(cands, key=lambda i: len(i["nome"]))
        parts.append(f"{best['nome']} (R$ {best['pdv']:.2f})")
    return "Destaques: " + " • ".join(parts)


HIGHLIGHTS = build_highlights()


SYSTEM = (
    "Você é o atendente virtual da Chiquinho Sorvetes de Teresópolis (RJ). "
    "Responda em português, curto, simpático e com emojis leves. "
    "HORÁRIO OFICIAL DA LOJA: aberta de segunda a segunda (todos os dias), "
    "das 10:30 às 21:00 (fonte: perfil oficial da loja no Instagram). "
    "Quando o cliente perguntar por produtos, use APENAS os preços do cardápio "
    "fornecido na mensagem de contexto. Produtos marcados como INDISPONÍVEL não "
    "estão à venda nesta loja — avise isso com educação e ofereça uma alternativa "
    "parecida do cardápio. NUNCA invente preço, sabor ou produto. Se o item não "
    "estiver na lista, diga que pode confirmar na loja (WhatsApp/Instagram). "
    "Sugira os destaques quando fizer sentido. Não informe endereço se não estiver "
    "na lista de informações."
)


def tokenize(text):
    toks = re.findall(r"[a-zà-ú0-9]+", text.lower())
    return [t for t in toks if t not in STOPWORDS and len(t) > 1]


def search_menu(query, limit=8):
    toks = tokenize(query)
    if not toks:
        return []
    scored = []
    for item in INDEX:
        key = item["key"]
        hits = sum(1 for t in toks if t in key)
        if hits:
            scored.append((item, hits))
    scored.sort(key=lambda x: (-x[1], len(x[0]["nome"])))
    return scored[:limit]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(204); self._cors(); self.end_headers()

    def do_GET(self):
        if self.path.startswith("/assets/"):
            asset = (Path(__file__).parent / self.path.lstrip("/")).resolve()
            root = (Path(__file__).parent / "assets").resolve()
            if asset.is_file() and root in asset.parents:
                ctype = {".png": "image/png", ".jpg": "image/jpeg", ".svg": "image/svg+xml"}
                self.send_response(200)
                self.send_header("Content-Type", ctype.get(asset.suffix, "application/octet-stream"))
                self.send_header("Cache-Control", "max-age=3600")
                self._cors(); self.end_headers()
                self.wfile.write(asset.read_bytes())
                return
            self.send_response(404); self.end_headers(); return
        if self.path in ("/", "/index.html"):
            html = (Path(__file__).parent / "index.html").read_text("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self._cors(); self.end_headers()
            self.wfile.write(html.encode("utf-8"))
        else:
            self.send_response(404); self.end_headers()

    def do_POST(self):
        if self.path != "/chat":
            self.send_response(404); self.end_headers(); return
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            history = body.get("history", [])[-8:]

            # última mensagem do cliente para buscar no cardápio
            last_user = ""
            for m in reversed(history):
                if m.get("role") == "user":
                    last_user = m["content"]; break

            # Pergunta de horário → resposta determinística (nunca deixar o LLM
            # inventar horário; mesma lição do preço indisponível).
            if HOURS_RE.search(last_user):
                reply = ("Funcionamos todos os dias (segunda a segunda), das "
                         "10:30 às 21:00. 😊 Fonte: perfil oficial da loja no "
                         "Instagram.")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self._cors(); self.end_headers()
                self.wfile.write(json.dumps({"reply": reply}).encode())
                return

            # Pergunta de localização → aponta para o botão Mapa (sem inventar endereço).
            if ADDRESS_RE.search(last_user):
                reply = ("Ficamos em Teresópolis (RJ)! 📍 Para ver nossa localização e "
                         "traçar a rota, toque no botão \"Mapa\" da página inicial do "
                         "site. Precisa de mais alguma coisa? 😊")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self._cors(); self.end_headers()
                self.wfile.write(json.dumps({"reply": reply}).encode())
                return

            # Pedido genérico de cardápio (sem produto específico) → resumo determinístico.
            if MENU_RE.search(last_user) and not has_group_name(last_user):
                reply = MENU_SUMMARY + "\n\n" + HIGHLIGHTS
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self._cors(); self.end_headers()
                self.wfile.write(json.dumps({"reply": reply}).encode())
                return

            scored = search_menu(last_user)
            hits = [it for it, _ in scored]
            menu_ctx = HIGHLIGHTS

            # Se o melhor match (topo da pontuação) é só indisponível: resposta
            # determinística, sem chamar o LLM (impossível inventar preço).
            if scored:
                best_score = scored[0][1]
                top_tier = [it for it, s in scored if s == best_score]
                if top_tier and all(not it["disp"] for it in top_tier):
                    nome = top_tier[0]["nome"]
                    grupo = top_tier[0]["grupo"]
                    alt = [i for i in INDEX if i["disp"] and i["grupo"] == grupo][:3]
                    if alt:
                        opcoes = ", ".join(f"{a['nome']} (R$ {a['pdv']:.2f})" for a in alt)
                        reply = (f"Esse produto ({nome}) não está disponível nesta loja no "
                                 f"momento. 😊 Mas temos opções parecidas: {opcoes}. "
                                 "Quer saber mais sobre alguma?")
                    else:
                        reply = (f"Esse produto ({nome}) não está disponível nesta loja no "
                                 "momento. 😊 Posso ajudar com outra coisa?")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self._cors(); self.end_headers()
                    self.wfile.write(json.dumps({"reply": reply}).encode())
                    return

            if hits:
                lines = []
                for h in hits:
                    if h["disp"]:
                        lines.append(f"{h['nome']}: R$ {h['pdv']:.2f}")
                    else:
                        lines.append(f"{h['nome']}: INDISPONÍVEL nesta loja")
                menu_ctx += "\nProdutos encontrados: " + " | ".join(lines)
                menu_ctx += ("\nREGRAS: cite preço apenas de produtos com preço listado. "
                             "Produtos marcados INDISPONÍVEL não têm preço — nunca invente.")

            messages = [
                {"role": "system", "content": SYSTEM},
                {"role": "system", "content": "CARDÁPIO (use estes preços):\n" + menu_ctx},
            ]
            messages.extend(history)

            if API_KEY:
                # OpenCode Zen — deepseek-v4-flash-free (rápido)
                req = urllib.request.Request(
                    OPENCODE_URL,
                    data=json.dumps({
                        "model": OPENCODE_MODEL, "messages": messages,
                        "stream": False, "temperature": 0.3, "max_tokens": 800,
                    }).encode(),
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": "Bearer " + API_KEY,
                        "User-Agent": "chiquinho-atendente/1.0",
                    },
                )
                with urllib.request.urlopen(req, timeout=180) as resp:
                    data = json.loads(resp.read())
                reply = (data.get("choices", [{}])[0].get("message", {})
                         .get("content", "") or "").strip() or "(sem resposta)"
            else:
                # Fallback: Ollama local
                req = urllib.request.Request(
                    OLLAMA_URL,
                    data=json.dumps({
                        "model": OLLAMA_MODEL, "messages": messages,
                        "stream": False,
                        "options": {"temperature": 0.3, "num_ctx": 32768},
                    }).encode(),
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=180) as resp:
                    data = json.loads(resp.read())
                reply = data.get("message", {}).get("content", "(sem resposta)")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self._cors(); self.end_headers()
            self.wfile.write(json.dumps({"reply": reply}).encode())
        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self._cors(); self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())


if __name__ == "__main__":
    print(f"Chiquinho Sorvetes Teresópolis demo em http://127.0.0.1:{PORT} (Ctrl+C p/ parar)")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
