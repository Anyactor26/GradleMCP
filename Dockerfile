FROM python:3.11-slim-bookworm
# The API controls Docker and must be trusted. No socket is ever mounted in workers.
RUN apt-get update && apt-get install -y --no-install-recommends docker.io \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE NOTICE ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable
ENV PATH="/app/.venv/bin:$PATH" GRADLEMCP_HOST=0.0.0.0
WORKDIR /var/lib/gradlemcp
EXPOSE 8000
ENTRYPOINT ["gradlemcp"]
CMD ["serve"]
