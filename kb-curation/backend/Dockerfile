FROM python:3.11-slim
# pdftotext is used when importing a scope topic list from a PDF.
RUN apt-get update && apt-get install -y --no-install-recommends poppler-utils \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
ENV KB_DATA_DIR=/data PYTHONUNBUFFERED=1
EXPOSE 8000
# One worker only: the crawl scheduler runs inside the API process.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
