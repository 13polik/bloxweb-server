FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py storage.py bot_ai.py arena.json ./
COPY public/ ./public/
ENV PORT=8093 DATA_DIR=/data
RUN mkdir /data && useradd --system blox && chown blox /data /app
USER blox
EXPOSE 8093
CMD ["python3", "server.py"]
