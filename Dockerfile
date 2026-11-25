FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    ISTIBAQ_DB=/data/istibaq.db

WORKDIR /app
COPY pyproject.toml README.md ./
COPY istibaq ./istibaq
RUN apt-get update && apt-get install -y --no-install-recommends libatomic1 libgomp1 \
 && pip install --no-cache-dir '.[service,capture]' \
 && python -m playwright install --with-deps chromium \
 && rm -rf /var/lib/apt/lists/*

EXPOSE 8080
CMD ["uvicorn", "istibaq.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080"]
