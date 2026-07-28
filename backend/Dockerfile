# Development image for docker-compose local-dev.
# Production should use scripts/runtime/production-up.sh or a dedicated runtime image;
# this file intentionally installs dev extras and runs uvicorn with --reload.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml requirements.lock README.md ./
COPY app ./app
COPY fixtures ./fixtures
COPY scripts ./scripts

RUN pip install --require-hashes -r requirements.lock

EXPOSE 8011

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8011", "--reload"]
