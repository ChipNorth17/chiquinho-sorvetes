# Chiquinho Sorvetes Teresópolis — atendente virtual (Cloud Run)
FROM python:3.11-slim

WORKDIR /app

# Só o necessário para rodar (menu_index.json é o cardápio compilado)
COPY server.py index.html menu_index.json ./
COPY assets ./assets

# Chave da API NÃO vai na imagem: passa como env var no deploy
ENV PORT=8080

EXPOSE 8080

CMD ["python3", "server.py"]
