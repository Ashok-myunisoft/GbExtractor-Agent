# ---------- Base Image ----------
FROM python:3.11-slim

# ---------- System Dependencies ----------
RUN apt-get update && apt-get install -y \
    build-essential \
    poppler-utils \
    tesseract-ocr \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# ---------- Working Directory ----------
WORKDIR /app

# ---------- Install Python Dependencies ----------
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ---------- Copy Project Files ----------
COPY . .

# ---------- Environment ----------
ENV PYTHONUNBUFFERED=1
ENV PORT=8005

# ---------- Expose Port ----------
EXPOSE 8005

# ---------- Run Application ----------
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8005"]
