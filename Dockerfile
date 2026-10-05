# Copiloto de Trades — imagem para homelab (Linux).
# O MetaTrader 5 NÃO roda aqui: para ordens reais, rode o agente MT5 no Windows (veja README).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=America/Sao_Paulo \
    COPILOTO_DATA_DIR=/data \
    COPILOTO_CONFIG_DIR=/app/config

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-lab.txt ./
# INSTALL_LAB=true instala TimesFM (torch CPU) e ferramentas do YouTube — imagem bem maior
ARG INSTALL_LAB=false
RUN pip install -r requirements.txt "gunicorn>=22" \
 && if [ "$INSTALL_LAB" = "true" ]; then \
      pip install torch --index-url https://download.pytorch.org/whl/cpu \
      && pip install "timesfm>=2.0" "yt-dlp>=2024.0" "youtube-transcript-api>=1.0"; \
    fi

COPY . .

RUN useradd --uid 1000 --create-home copiloto \
 && mkdir -p /data \
 && chown -R copiloto:copiloto /data /app/strategies /app/config
USER copiloto

EXPOSE 5000
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5000/api/health', timeout=4).status == 200 else 1)"

# 1 worker (o monitor de sinais é uma thread do processo) + threads para as requisições
CMD ["gunicorn", "--workers", "1", "--threads", "8", "--bind", "0.0.0.0:5000", "--timeout", "180", "--access-logfile", "-", "wsgi:app"]
