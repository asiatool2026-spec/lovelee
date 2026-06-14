FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py lbox_scraper.py rag_engine.py ./
COPY index.html index.css index.js ./

RUN mkdir -p data/lbox_cases data/chroma_db

EXPOSE 8080

CMD ["python3", "app.py"]
