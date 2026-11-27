# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    FLASK_APP=wsgi:app \
    DATA_DIR=/data

WORKDIR /app

RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /data \
    && chown appuser:appuser /data

# Dependencies first so code-only changes reuse this layer.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY --chown=appuser:appuser wsgi.py gunicorn.conf.py ./
COPY --chown=appuser:appuser app/ app/
COPY --chown=appuser:appuser migrations/ migrations/
COPY --chown=appuser:appuser docker/ docker/

USER appuser

EXPOSE 8000
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)"]

ENTRYPOINT ["sh", "docker/entrypoint.sh"]
