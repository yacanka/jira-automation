# Review Findings Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Fix the eight findings approved in the repository review, preserving existing public contracts and user changes.

**Architecture:** Keep the shared YAML/Python runner. Validate scenario semantics before execution, make expectations independent of Python optimization, and aggregate pytest phases once for CLI and GUI. Bind GUI execution identity and target to the actual request.

**Tech Stack:** Python 3.11+, pytest, Playwright, Tkinter; no new dependencies.

**Spec:** The eight P1/P2 findings in the preceding review and the user's instruction to fix all of them.

## Constraints and decisions

- Work in the existing dirty feature branch; preserve all prior edits. No resets, deletes, commits or external Jira writes.
- Retain CLI arguments, YAML action names, result fields and ownership restrictions.
- User authorization already covers implementation; no additional plan approval is needed.
- Product roadmap features (tags, installers, environment mapping) are outside these eight fixes.
- Keep a record here instead of creating extra workflow state in the repository.

## Review focus

- Real null versus missing field, and invalid schema types before any fixture allocation.
- Expectations in an optimized worker process.
- Collection errors and skipped tests containing sensitive diagnostic data.
- Setup/call/teardown failure precedence, cancellation and incomplete runs across both frontends.
- External Python paths, parameterized selectors, and historical target configuration.

## Tasks

### 1. Scenario correctness and UI creation evidence

Files: `scenario.py`, `runner.py`, `client.py`, `ui.py`, related runner/schema/client/UI tests.

- [x] Add regressions for missing/null fields, optimized execution, invalid expectation context/types, and creation verification failure.
- [x] Run regressions and confirm the reported failures.
- [x] Implement explicit expectations, preflight checks, and creation tracking separate from ownership.
- [x] Run module tests and validate all existing examples.

### 2. Unified outcomes and report redaction

Files: `pytest_plugin.py`, `gui/pytest_bridge.py`, a focused outcome module if necessary, CLI/worker tests.

- [x] Add subprocess regressions for collection masking, teardown, skip and unexpected YAML errors.
- [x] Confirm failures, then centralize final outcome aggregation and sanitize collection reports before JUnit consumes them.
- [x] Run CLI and GUI worker tests, preserving blocked/canceled semantics.

### 3. GUI execution identity and target

Files: `gui/app.py`, `gui/run_view.py`, `gui/pytest_bridge.py`, `gui/rerun.py`, GUI model/worker/smoke tests.

- [x] Add regressions for workspace-external Python selection and exact historical target display.
- [x] Confirm failures, then preserve executable selectors and freeze the request target in the run view.
- [x] Verify parameterized selections, reruns and regular execution.

### 4. Verification and documentation

- [x] Correct the weak malformed-scenario test baselines; format reported files and ignore `.DS_Store`.
- [x] Document relevant validation, report and rerun semantics.
- [x] Run full pytest, browser regressions, Ruff lint/format, mypy, pip check, example validation/collection and isolated build.
- [x] Obtain a final focused review and address material findings with regressions.

## Progress

- Baseline: 160 offline tests and 31 browser tests passed during review; seven formatting failures. Tk unavailable in the existing virtual environment.

- Completed all eight approved findings without new dependencies; existing working-tree changes were preserved.
- Independent final review found one additional outcome edge case: interrupted teardown retained a successful call result. CLI and GUI subprocess regressions reproduced the false pass, then passed after requiring teardown completion. No other critical or important findings were confirmed.
- Final validation: 193 offline tests, 31 local Chrome browser tests, Ruff lint and repository-wide format checks, mypy (36 source files), dependency consistency, 20 YAML examples, six Python example collections, and isolated sdist/wheel build with packaged import/resource checks.
- GUI controller/worker behavior was verified without Tk widgets. Real Tk desktop rendering, Windows behavior, and live Jira integration remain unverified in this environment; no live Jira operations were performed.
