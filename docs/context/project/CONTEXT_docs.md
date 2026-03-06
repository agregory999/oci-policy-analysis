# Project-Specific Context: Documentation

This file defines documentation practices, conventions, and rules unique to this repository. Consult it to ensure all new code, features, and modules are documented in line with project requirements.

---

## 1. Area Overview

Documentation for this project includes:
- Markdown docs under `docs/source/` (overview, architecture, usage, logging, etc.)
- API reference, built via Sphinx or similar tools when applicable
- Embedded docstrings for all public classes, functions, modules

---

## 2. Doc Evolution Notes

- All major feature merges must include/add relevant docs in `docs/source/`
- Revisions and additions should be cross-referenced in CHANGELOG.md and relevant CONTEXT files for traceability
- Architecture and UI overviews must be updated on major refactors

---

## 3. Local Documentation Standards

- Use reStructuredText for main docs if generating API references, Markdown for conceptual/quickstart content
- All user-facing features must be discoverable from `docs/source/index.rst`
- Diagrams and illustrations (e.g. Drawio, SVG) go in `docs/source/` or nested `docs/source/_static/`

---

## 4. Overrides from Generic Patterns

- Any special documentation hooks or deployment steps are described here and take priority over generic guidelines

---

_For global/generic documentation patterns, see [../generic/GENERIC_README.md](../generic/GENERIC_README.md)._
