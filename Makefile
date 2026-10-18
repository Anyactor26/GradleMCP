.PHONY: install format lint typecheck test integration serve docker config openapi release audit
install:
	uv sync --locked
format:
	uv run ruff format src tests examples/client.py
	uv run ruff check src tests examples/client.py --fix
lint:
	sh -n install.sh
	sh -n scripts/install-docker.sh
	uv run ruff check src tests examples/client.py
	uv run ruff format --check src tests examples/client.py
typecheck:
	uv run mypy src/gradlemcp
test:
	uv run pytest -m 'not docker'
integration:
	GRADLEMCP_DOCKER_TESTS=1 uv run pytest -m docker -v
serve:
	uv run gradlemcp serve
config:
	uv run gradlemcp config validate
docker:
	docker compose up --build -d
openapi:
	uv run gradlemcp export-openapi
release:
	uv build
audit:
	uv run pip-audit --skip-editable --progress-spinner off
