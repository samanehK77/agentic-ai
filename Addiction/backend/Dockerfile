# Backend image (optional compose profile "app"). Build from the project folder (Addiction/):
#     docker build -f backend/Dockerfile -t mindevidence-api .
# What is NOT in the image: .env, PDFs, model caches, tests, the virtual environment (see .dockerignore). Secrets reach the
# container only through env_file / environment at run time. Runs as an unprivileged user.
FROM python:3.13-slim

# false = lightweight (no torch: search and RAG answers return 503 until you use the heavier image or a host-side API)
# true  = CPU-only torch + sentence-transformers for query embedding (several hundred MB more)
ARG WITH_EMBEDDINGS=false

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin app
WORKDIR /srv/backend

COPY backend/requirements.txt backend/requirements-embeddings.txt ./
RUN pip install -r requirements.txt \
 && if [ "$WITH_EMBEDDINGS" = "true" ]; then \
        pip install torch --index-url https://download.pytorch.org/whl/cpu \
     && pip install -r requirements-embeddings.txt; \
    fi

COPY backend/ ./
RUN mkdir -p /srv/data /srv/backend/models && chown -R app:app /srv
USER app

EXPOSE 8001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
