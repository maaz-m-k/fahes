# One image serves everything: the desk (web/, built here in real engine mode) at /, the engine API under /api.

# ---- the desk
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
# the desk reads the voice session settings from the engine package (one source)
COPY istibaq/voice/session.json /istibaq/voice/session.json
ENV VITE_ENGINE=http
RUN npx vite build

# ---- the engine
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    ISTIBAQ_DB=/data/istibaq.db \
    ISTIBAQ_WEB_DIST=/app/web/dist

WORKDIR /app
COPY pyproject.toml README.md ./
COPY istibaq ./istibaq
# ffmpeg makes the sped-up footage; Chromium (Playwright) is for capture and recording
RUN apt-get update && apt-get install -y --no-install-recommends libatomic1 libgomp1 ffmpeg \
 && pip install --no-cache-dir '.[service,capture]' \
 && python -m playwright install --with-deps chromium \
 && rm -rf /var/lib/apt/lists/*
COPY --from=web /web/dist ./web/dist

EXPOSE 8080
CMD ["uvicorn", "istibaq.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080"]
