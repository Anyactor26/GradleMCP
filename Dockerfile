# A modern standalone CLI can negotiate with newly installed Docker Engines.
# Pin these reviewed image tags to digests for production provenance.
ARG DOCKER_CLI_IMAGE=docker:28-cli
FROM ${DOCKER_CLI_IMAGE} AS docker_cli
FROM python:3.11-slim-bookworm
# The API controls Docker and must be trusted. No socket is ever mounted in workers.
# Copy only the client, not a daemon or Debian's older docker.io package.
COPY --from=docker_cli /usr/local/bin/docker /usr/local/bin/docker
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
