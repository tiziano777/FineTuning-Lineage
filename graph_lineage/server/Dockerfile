FROM python:3.10-slim

WORKDIR /app

# Copia i requisiti dalla radice del progetto
COPY graph_lineage/server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia tutto il contenuto della radice (incluso graph_lineage/)
COPY . .

# Indica a Python dove cercare i pacchetti per risolvere gli import parent
ENV PYTHONPATH=/app

EXPOSE 8502

CMD ["uvicorn", "graph_lineage.server.app:app", "--host", "0.0.0.0", "--port", "8502"]