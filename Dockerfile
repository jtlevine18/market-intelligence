FROM python:3.11-slim
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# Install PyTorch CPU-only (needed for sentence-transformers)
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download Chronos-2 model into HF cache so pipeline loads from disk
# Must run AFTER pip install (needs huggingface_hub + chronos-forecasting)
RUN python -c "\
from huggingface_hub import snapshot_download; \
print('Downloading chronos-bolt-base...'); \
snapshot_download('amazon/chronos-bolt-base'); \
print('Done.')" && echo "Chronos model cached" || echo "WARN: Chronos pre-download failed"

COPY config.py .
COPY src/ src/
COPY markets.json commodities.json farmers.json ./
RUN mkdir -p models

RUN adduser --disabled-password --gecos '' appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=10s --retries=5 --start-period=60s \
    CMD curl -f http://localhost:7860/health || exit 1

CMD ["python", "-m", "uvicorn", "src.api:app", "--host", "0.0.0.0", "--port", "7860"]
