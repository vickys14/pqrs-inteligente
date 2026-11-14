FROM python:3.11-slim

# Tesseract (OCR) con el idioma español
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-spa \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Librerias del reporte en PDF (capa aparte para no reinstalar lo anterior)
RUN pip install --no-cache-dir matplotlib reportlab

COPY . .
CMD ["python", "main.py"]
