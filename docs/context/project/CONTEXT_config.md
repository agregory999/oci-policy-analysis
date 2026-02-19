# Project-Specific Context: Configuration and Quality Automation

This file describes configuration, CI/CD, and code quality automation rules specific to this repository. Use it to understand how this project enforces and customizes best practices for Python linting, formatting, pre-commit hooks, and semantic versioning.

---

## 1. Area Overview

Project configuration lives in the following files:
- `ruff.toml` — lint and code style rules
- `.pre-commit-config.yaml` — pre-commit hooks for autoformatting, commit checks, etc.
- `CHANGELOG.md` — human- and machine-readable changelog
- `pyproject.toml` — packaging, build, and secondary tool integration

---

## 2. Historical/Process Notes

- The ruff configuration enforces a strict superset of PEP8 and is updated with each major refactor.
- Pre-commit hooks are **required** for all contributors; see `.pre-commit-config.yaml` for current set (includes Ruff, whitespace cleanup, conventional commit checks).
- All releases and PR merges to main should use [semantic-release](https://semantic-release.gitbook.io/semantic-release/) workflow, bumping version based on commit messages.

---

## 3. Local Code Quality Standards

- No new code is accepted unless it passes Ruff and all pre-commit hooks
- All contributors must:
    - Run `pre-commit install` after cloning
    - Pass all hooks locally before PR submission

---

## 4. Differences from Generic Guidance

- New configuration files should always be documented and referenced here
- Project overrides/additional rules here take priority over [../generic/GENERIC_CODING_STANDARDS.md](../generic/GENERIC_CODING_STANDARDS.md)

---

**For specific config examples and additions, update this file during major workflow/process changes.**
