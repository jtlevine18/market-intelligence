FROM python:3.11-slim
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# Install PyTorch CPU-only (needed for sentence-transformers)
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create appuser first so we can download the model to the right cache dir
RUN adduser --disabled-password --gecos '' appuser

# Pre-download Chronos-2 model as appuser so cache lands in /home/appuser/
USER appuser
ENV HF_HOME=/home/appuser/.cache/huggingface
RUN python -c "\
from huggingface_hub import snapshot_download; \
print('Downloading chronos-bolt-tiny...'); \
snapshot_download('amazon/chronos-bolt-tiny'); \
print('Chronos model cached.')"

# Switch back to root to copy files and set permissions
USER root
COPY config.py .
COPY src/ src/
COPY markets.json commodities.json farmers.json ./
RUN mkdir -p models
RUN chown -R appuser:appuser /app

USER appuser

EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=10s --retries=5 --start-period=60s \
    CMD curl -f http://localhost:7860/health || exit 1

CMD ["python", "-m", "uvicorn", "src.api:app", "--host", "0.0.0.0", "--port", "7860"]
