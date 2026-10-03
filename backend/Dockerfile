FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    ACTIVEPIECES_PIECES_DIR=/app/pieces

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
COPY vendor ./vendor
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

RUN pip install ./vendor/en_core_web_sm-3.8.0-py3-none-any.whl

COPY app ./app
COPY scripts ./scripts
# Activepieces piece archives built by workflows/pieces (copied in by deploy.sh); installed at bootstrap.
COPY pieces ./pieces

RUN useradd --create-home --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /usr/local/lib/python3.11/site-packages/guardrails/hub \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD ["gunicorn", "app.main:app", "-k", "uvicorn.workers.UvicornWorker", "--workers", "2", "--bind", "0.0.0.0:8000", "--timeout", "60"]
