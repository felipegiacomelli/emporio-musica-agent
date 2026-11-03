.PHONY: install lint test run eval

install:
	uv sync --frozen
	uv run pre-commit install

lint:
	uv run ruff check .
	uv run black --check .
	uv run mypy emporio evals

test:
	uv run pytest --cov=emporio --cov-report=term-missing

run:
	uv run python -m emporio

eval:
	uv run python -m evals.run
