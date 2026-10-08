FROM node:24-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build
FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && pip install --no-deps --no-cache-dir xgboost-cpu==3.0.5 \
    && useradd -u 10001 -m qaif
COPY backend/ backend/
COPY fixtures/ fixtures/
COPY deploy/start.py deploy/start.py
COPY --from=frontend /app/frontend/dist frontend/dist
RUN mkdir /data && chown qaif:qaif /data
# The entry point prepares a mounted /data disk, then runs Uvicorn as qaif.
ENV QAIF_DATA_DIR=/data QAIF_DEMO_MODE=true QAIF_SECURE_COOKIE=true QAIF_PUBLIC_DEPLOYMENT=true \
    PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
EXPOSE 8765
CMD ["python","deploy/start.py"]
