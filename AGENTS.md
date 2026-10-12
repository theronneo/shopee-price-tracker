# Repository Guidelines

## Superpowers Workflow

Use installed Superpowers skills by default. Begin with
`superpowers:using-superpowers`, then read the relevant skill before acting.
Use `superpowers:brainstorming` for new behavior, `superpowers:writing-plans` for
multi-step changes, and `superpowers:executing-plans` for approved plans.
Apply `superpowers:systematic-debugging` to defects,
`superpowers:test-driven-development` to meaningful behavior, and
`superpowers:verification-before-completion` before reporting success.
Use `superpowers:requesting-code-review` for an independent review of substantial
changes. User instructions take precedence over skill defaults.

If Superpowers is unavailable, identify the missing workflow and ask the user to
enable the plugin in their agent environment. Do not silently install plugins or
change global settings. Reference skills by name, not machine-specific paths.

## Project Structure

`src/shopee_tracker/` contains configuration, domain types, SQLite persistence,
Telegram handling, scheduling, browser access, and the CLI. `tests/` contains
unittest cases and labelled fixtures. `scripts/check.py` runs the local checks.
`docs/superpowers/` contains the design, plan, and execution record. Private runtime
files belong in the ignored `data/` directory.

## Setup and Commands

Use Python 3.11+ and a local virtual environment. Install pinned dependencies with
`uv pip sync --require-hashes requirements-dev.lock`, then install the package with
`uv pip install --no-deps --no-build-isolation -e .`.

Run `playwright install chromium` and `shopee-tracker browser-setup` for login.
`shopee-tracker run` starts tracking; `shopee-tracker price-check <url>` diagnoses a
real product without adding watches. Run `python scripts/check.py` for Ruff,
strict mypy, and the full test suite. Use `ruff format .` to format changes and
`uv build --no-build-isolation` to build distributions.

## Coding and Tests

Use four-space indentation, snake_case functions and modules, PascalCase types,
and type hints. Keep HTTP, browser access, persistence, and price rules separate.
Store prices as integer SGD cents and preserve exact variant identity.

Name tests `tests/test_*.py`; run them with `python -m unittest discover -s tests -v`.
Use real SQLite for persistence tests and replace only external boundaries.
Cover restart recovery, failed reads, retries, access restrictions, and untracking
races. Synthetic fixtures never establish live Shopee compatibility.

## Contributions and Configuration

Use imperative commit subjects and describe behavior, verification, and remaining
limitations in pull requests. Keep tokens, browser sessions, databases, and account
data out of commits and logs. Document new settings in `.env.example` without
secrets. Preserve existing runtime data when changing application code.
