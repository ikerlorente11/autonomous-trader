# Backend test/quality targets. Everything runs inside the running `trader-api`
# container (Python 3.12 + deps); the test DB is a separate database on the same
# TimescaleDB server. See docs/qa/testing-strategy.md.

CONTAINER ?= trader-api
DEV_DEPS  := pip install -q -r backend/requirements-dev.txt

.PHONY: test test-unit test-int test-reg lint typecheck cov install-hooks

test:                       ## full suite (unit + integration + regression)
	./scripts/test.sh

test-unit:                  ## pure logic only — fast, no DB
	./scripts/test.sh unit

test-int:                   ## DB-backed integration tests
	./scripts/test.sh integration

test-reg:                   ## regression guards for previously-fixed bugs
	./scripts/test.sh regression

cov:                        ## full suite with coverage report
	docker exec $(CONTAINER) sh -lc "$(DEV_DEPS) && sh scripts/setup-test-db.sh && \
		python -m pytest --cov=backend --cov-report=term-missing"

# Scoped to the test suite this task owns; the wider backend has pre-existing ruff/mypy
# debt (import order, a few unused imports) that is a separate cleanup.
lint:                       ## ruff (test suite)
	docker exec $(CONTAINER) sh -lc "$(DEV_DEPS) && ruff check backend/tests"

typecheck:                  ## mypy (test suite) — follow-imports=skip to fit the Pi's RAM
	docker exec $(CONTAINER) sh -lc "$(DEV_DEPS) && \
		mypy backend/tests --follow-imports=skip --ignore-missing-imports --no-incremental"

install-hooks:              ## symlink the pre-push hook into .git/hooks
	chmod +x scripts/hooks/pre-push
	ln -sf ../../scripts/hooks/pre-push .git/hooks/pre-push
	@echo "pre-push hook installed (runs unit + regression before every push)"
