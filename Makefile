# Makefile — common dev tasks.
# Run `make help` to see available targets.

PYTHON ?= python3

.PHONY: help lint-runs lint-runs-strict test-persistence

help:  ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

lint-runs:  ## Lint runs/ for ADR I1-I9 invariant violations (non-strict; warn on pre-P2b/P4)
	$(PYTHON) scripts/lint_runs.py

lint-runs-strict:  ## Lint runs/ in strict mode — I7/I9 warnings become errors (use post-P2b/P4)
	$(PYTHON) scripts/lint_runs.py --strict

test-persistence:  ## Run sidecar_io + validate unit tests
	$(PYTHON) -m pytest harness/persistence/test_sidecar_io.py harness/persistence/test_validate.py -v
