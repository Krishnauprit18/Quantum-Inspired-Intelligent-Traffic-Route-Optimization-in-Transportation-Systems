.PHONY: install test lint security verify api prod-up prod-down
install:
	python -m pip install -e ".[service,ortools,benchmark,dev]"

test:
	pytest --cov=quantroute --cov-report=term-missing

lint:
	ruff check .

security:
	bandit -c pyproject.toml -r src
	pip-audit

verify: lint test security

api:
	quantroute-api

prod-up:
	docker compose up -d --build

prod-down:
	docker compose down
