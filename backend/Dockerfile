FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps for bcrypt, reportlab image handling, healthcheck curl.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libjpeg-dev zlib1g-dev curl \
    && rm -rf /var/lib/apt/lists/*

# Copy backend source (context is /app/backend from docker-compose)
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . ./

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
  CMD curl -fsS http://127.0.0.1:8001/api/ || exit 1

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8001", "--proxy-headers", "--forwarded-allow-ips=*"]
