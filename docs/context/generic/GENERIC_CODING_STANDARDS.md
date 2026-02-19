# Generic Coding Standards and Quality Automation

This document establishes universal Python coding standards and quality automation practices for all OCI App and analytical Python projects derived from this repository’s ecosystem.

---

## Python Code Style

- Use PEP8 as a base with project-specific overrides (see Ruff config)
- 4-space indentation, max line length 120
- Descriptive names for all classes, functions, and variables
- Document all public APIs and complex logic paths
- Type annotations are strongly encouraged for all functions and methods

---

## Automated Linting and Formatting

- **Ruff**: All code must pass lint and autoformat checks via Ruff, using project/configured rules (see `ruff.toml`)
- Add Ruff as a pre-commit hook
- No code is merged unless it passes full lint suite

---

## Pre-commit Hooks

- Use `.pre-commit-config.yaml` to enforce:
    - Ruff lint/format
    - Remove trailing whitespace
    - Validate commit message style (see below)
- All contributors must install pre-commit, run `pre-commit install`, and locally fix issues before push

---

## Commit Messages and Semantic Versioning

- Enforce [Conventional Commits](https://www.conventionalcommits.org/) (e.g., `feat:`, `fix:`, `chore:`, `docs:`)
- Each merge to main branch updates the `CHANGELOG.md` and uses [semantic-release](https://semantic-release.gitbook.io/) (auto or manual) to bump version and publish

---

## Checklist for New Code

- [ ] Follows all above style/lint/commit message rules
- [ ] Has docstrings for public surfaces
- [ ] Passes pre-commit hooks
- [ ] Described in CHANGELOG with proper message

---

See also: [GENERIC_README.md](GENERIC_README.md) and local project overrides in [../project/CONTEXT_config.md](../project/CONTEXT_config.md).
