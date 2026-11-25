# NavIC single-service production image.
#
# Stage 1 builds the React/Vite frontend; stage 2 runs FastAPI, which serves
# that build from frontend/vite/build alongside the REST API and WebSocket.

# Node 26 matches the local toolchain (npm 11); npm 10 rejects the existing
# @eslint/js@10 / eslint@9 peer range in package-lock.json.
FROM node:26-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt

COPY backend/ backend/
COPY navic_tcp/ navic_tcp/
COPY config/ config/
COPY VERSION VERSION
COPY scripts/render_start.sh scripts/render_start.sh
COPY --from=frontend /app/frontend/vite/build frontend/vite/build

RUN useradd --create-home --uid 10001 navic && chown -R navic:navic /app
USER navic

# Render (and most hosts) inject PORT; the backend settings read it.
ENV PORT=8000
EXPOSE 8000
CMD ["sh", "scripts/render_start.sh"]
