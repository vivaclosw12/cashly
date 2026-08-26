FROM mcr.microsoft.com/playwright/python:v1.55.0-noble

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .

RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8080}"]
