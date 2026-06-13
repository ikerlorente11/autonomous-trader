# Backend test/quality targets. Everything runs in a throwaway container from the
# app image with the working tree bind-mounted (scripts/test.sh) — the live
# trader-api is the production container (baked code, no test harness), so exec-ing
# into it would test the deploy, not your edits. The test DB is a separate database
# on the same TimescaleDB server. See docs/qa/testing-strategy.md.

IMAGE    ?= docker-api:latest
NETWORK  ?= docker_default
DEV_DEPS := pip install -q -r backend/requirements-dev.txt
RUN_UNIT := docker run --rm -v $(CURDIR):/app -w /app \
	-e DATABASE_URL='postgresql+asyncpg://test:test@localhost:5/test' $(IMAGE)
RUN_DB   := docker run --rm -v $(CURDIR):/app -w /app \
	--network $(NETWORK) --env-file $(CURDIR)/.env $(IMAGE)

.PHONY: test test-unit test-int test-reg lint typecheck cov install-hooks backtest

# e.g.: make backtest LABELS=v3,v4,v5 START=2024-09-02
LABELS ?= v1,v3,v4,v5,v6
START  ?= 2024-09-02
backtest:                   ## replay strategy versions over stored history
	docker run --rm -v $(CURDIR):/app -w /app -e PYTHONPATH=/app \
		--network $(NETWORK) --env-file $(CURDIR)/.env $(IMAGE) \
		python -m backend.backtest --labels $(LABELS) --start $(START)

test:                       ## full suite (unit + integration + regression)
	./scripts/test.sh

test-unit:                  ## pure logic only — fast, no DB
	./scripts/test.sh unit

test-int:                   ## DB-backed integration tests
	./scripts/test.sh integration

test-reg:                   ## regression guards for previously-fixed bugs
	./scripts/test.sh regression

cov:                        ## full suite with coverage report
	$(RUN_DB) sh -c "$(DEV_DEPS) && sh scripts/setup-test-db.sh && \
		python -m pytest --cov=backend --cov-report=term-missing"

# Scoped to the test suite this task owns; the wider backend has pre-existing ruff/mypy
# debt (import order, a few unused imports) that is a separate cleanup.
lint:                       ## ruff (test suite)
	$(RUN_UNIT) sh -c "$(DEV_DEPS) && python -m ruff check backend/tests"

typecheck:                  ## mypy (test suite) — follow-imports=skip to fit the Pi's RAM
	$(RUN_UNIT) sh -c "$(DEV_DEPS) && \
		python -m mypy backend/tests --follow-imports=skip --ignore-missing-imports --no-incremental"

install-hooks:              ## symlink the pre-push hook into .git/hooks
	chmod +x scripts/hooks/pre-push
	ln -sf ../../scripts/hooks/pre-push .git/hooks/pre-push
	@echo "pre-push hook installed (runs unit + regression before every push)"
