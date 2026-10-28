SHELL := /bin/sh
PYTHON ?= python3
COMPOSE := docker compose
.PHONY: setup dev down migrate seed test eval lint typecheck build test-web test-e2e test-e2e-live test-postgres logs check-infra
setup:
	test -f .env || cp .env.example .env
	$(PYTHON) -m venv .venv
	.venv/bin/python -m pip install -r apps/api/requirements-dev.lock
	.venv/bin/python -m pip install --no-deps -e apps/api
	cd apps/web && npm ci

dev:
	$(MAKE) build
	$(COMPOSE) up --no-build --wait --wait-timeout 300
	@echo 'Application: http://localhost:3000 | API: http://localhost:8000/api/docs'
	@echo 'Next: make seed; see README for local demo accounts.'

down:
	$(COMPOSE) down

migrate:
	$(COMPOSE) run --rm migrate

seed:
	$(COMPOSE) run --rm migrate python -m app.seed

test:
	.venv/bin/python -m pytest apps/api/tests tests infrastructure/tests -q
	cd apps/web && npm test -- --run

eval:
	.venv/bin/python -m app.evaluation

lint:
	.venv/bin/ruff check apps/api tests
	cd apps/web && npm run lint

typecheck:
	.venv/bin/mypy --config-file apps/api/pyproject.toml apps/api/app
	cd apps/web && npm run typecheck

build:
	# API services share one tag; build it once, including with the classic builder.
	$(COMPOSE) build backend frontend minio

test-web:
	cd apps/web && npm test -- --run

test-e2e:
	cd apps/web && npm run test:e2e

test-e2e-live:
	cd apps/web && LIVE_E2E=true npm run test:e2e

test-postgres:
	@test -n "$$TEST_DATABASE_URL" || (echo 'Set TEST_DATABASE_URL to a migrated disposable PostgreSQL admin connection.' >&2; exit 1)
	.venv/bin/python -m pytest tests/integration -q

logs:
	$(COMPOSE) logs -f --tail=100 backend worker frontend

check-infra:
	ENV_FILE=.env.example $(COMPOSE) --env-file .env.example config --quiet
	terraform -chdir=infrastructure/terraform fmt -check -recursive
	terraform -chdir=infrastructure/terraform init -backend=false
	terraform -chdir=infrastructure/terraform validate
