FROM node:22-alpine AS frontend-build
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS application
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    TRANSFORMERS_CACHE=/models
WORKDIR /app
COPY pyproject.toml README.md THIRD_PARTY_NOTICES.md ./
COPY backend ./backend
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini
RUN pip install --no-cache-dir . && python -m playwright install --with-deps chromium
COPY --from=frontend-build /build/frontend/dist ./frontend/dist
RUN mkdir -p /data/db /data/uploads /data/generated /data/backups /models
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000 --workers 1"]
