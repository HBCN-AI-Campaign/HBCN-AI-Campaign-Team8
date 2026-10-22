# Build UI independently; no Node runtime is needed by the running service.
FROM node:22-bookworm-slim AS ui
WORKDIR /build/ui
COPY ui/package.json ui/package-lock.json ./
RUN npm ci
COPY ui/ ./
RUN npm run build

FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 RAG_DATA_DIR=/var/lib/hbcn-rag
WORKDIR /srv/rag
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates libstdc++6 fonts-dejavu-core fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ ./app/
COPY scripts/ ./scripts/
COPY contracts/ ./contracts/
COPY knowledge-base/catalog.json knowledge-base/README.md ./knowledge-base/
COPY --from=ui /build/app/static/ui-build/ ./app/static/ui-build/
RUN groupadd --gid 10001 rag && useradd --uid 10001 --gid rag --no-create-home rag \
    && mkdir -p /var/lib/hbcn-rag && chown rag:rag /var/lib/hbcn-rag
USER 10001:10001
EXPOSE 8011
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8011/health', timeout=3).read()"
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8011", "--workers", "1"]
