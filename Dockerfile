# ETL Observability App API
# Build from repo root:
#   docker build -t etl-obs-api -f Dockerfile .
# Run:
#   docker run --rm -p 8002:8002 --env-file .env etl-obs-api

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8002

WORKDIR /app

# System deps used by snowflake connector / SSL
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libssl-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY application/requirements.txt /app/application/requirements.txt
RUN pip install --upgrade pip && pip install -r /app/application/requirements.txt

# App code only (secrets via runtime env, not baked into image)
COPY application /app/application

EXPOSE 8002

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1

# Production: no --reload
CMD ["sh", "-c", "uvicorn application.src.app:app --host 0.0.0.0 --port ${PORT}"]
