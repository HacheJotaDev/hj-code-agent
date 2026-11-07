# HJ CODE AGENT V2 - imagen del orquestador (bot + API + workspaces)
# Los sandboxes de codigo se crean como contenedores HERMANOS (sibling) con
# docker CLI; el socket NO se monta dentro de los sandboxes, solo en este
# orquestador. Para maximo aislamiento usa Docker rootless en el host.
FROM python:3.12-slim

RUN apt-get update \
    && (apt-get install -y --no-install-recommends git ca-certificates docker-cli \
        || apt-get install -y --no-install-recommends git ca-certificates docker.io) \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY bot ./bot
COPY core ./core
COPY security ./security
COPY database ./database
RUN pip install --no-cache-dir .

ENV HJ_DATA_DIR=/data \
    HJ_WORKSPACES_DIR=/workspaces \
    HJ_BACKUPS_DIR=/backups \
    HJ_SANDBOX_BACKEND=docker

VOLUME ["/data", "/workspaces", "/backups"]
CMD ["python", "-m", "bot.main"]
