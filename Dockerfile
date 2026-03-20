FROM python:3.11-slim

WORKDIR /app

# System deps for python-magic, PyMuPDF, lxml
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmagic1 \
    libgl1 \
    libglib2.0-0 \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# OCR support: Tesseract + Poppler (for pdf2image)
RUN apt-get update && apt-get install -y tesseract-ocr tesseract-ocr-eng poppler-utils && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p data/uploads data/chroma

EXPOSE 8000

RUN chmod +x scripts/startup.sh

CMD ["scripts/startup.sh"]
