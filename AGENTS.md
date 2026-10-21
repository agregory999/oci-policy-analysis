# Project context

Package code is under `src/oci_policy_analysis`. The four interfaces are desktop Tkinter, CLI, FastAPI web, and FastMCP. Keep the published command names stable: `oci-policy-analysis-ui`, `oci-policy-analysis-cli`, `oci-policy-analysis-web`, and `oci-policy-analysis-mcp`.

## Architecture and public APIs

Shared models, repositories, parsers, engines, and support modules live under `application/core/`; use cases live under `application/services/`. The former top-level `oci_policy_analysis.common` and `.logic` compatibility packages were removed in 7.0. The top-level `.web` aliases are also removed; import web modules from `presentation/web` (the published web command remains unchanged). Use the maintained imports rather than recreating shims.

Prefer `AppContext` and focused services for reusable orchestration. Constructing a context does not load tenancy data. `LoadService` replaces the active snapshot and derived state; consumers should read the current context after reload instead of retaining old engines or corpora. The full post-load profile builds intelligence, corpora, permissions reports, and simulation; minimal builds query foundations and corpora without full recommendations or the permissions report; none skips enrichment.

The repository retains invalid/unresolved source evidence. Regular corpus facts and cross-tenancy relationships represent the tool's understanding of the loaded snapshot, not authoritative OCI policy-engine decisions. Keep conditions, exclusions, provenance, and data-coverage limitations visible. Canonical named principal keys are case-folded; original statement text and opaque identifiers retain their values.

Use Google/Napoleon docstrings for public classes and entry points: document arguments, attributes, returned data, and lifecycle/side effects where relevant. Maintain the explicit API reference under `docs/source/api/`. Architecture explanations belong in `docs/source/architecture.md`; Python embedding examples and lifecycle guidance belong in `docs/source/core_integration.md`.

## Saved data compatibility

The combined-cache format remains `version: 2`, with current writers using `schema_version: 3`. Existing `policies` and `policy_statements` sections remain required. Preserve supported older snapshots and defaults for absent optional fields. The 7.0 import-path break does not require discarding caches.

Corpora, intelligence overlays, and permissions reports are rebuilt at runtime rather than added to the combined-cache payload. Derived statement fields can change during enrichment. Legacy/incomplete association endpoints are reconstructed from source text on detached corpus copies. Do not rewrite source cache files as a side effect of querying or compiling a corpus. Changes to stored fields or load behavior need compatibility coverage and an explicit migration assessment.

## Local development and validation

Use `uv sync --extra web --extra mcp` for local dependencies and `run/local.sh [desktop|cli|web|mcp]` for source running. Add `--extra docs` for documentation tools and `--extra commit` for `pre_commit`/commit tooling. Dependencies and package metadata are maintained in `pyproject.toml`. `uv.lock` is generated locally and ignored; dependency resolution is not locked across checkouts.

Prefer focused pytest modules and Ruff for changed Python. Before shipping, run the full suite and project checks:

```bash
.venv/bin/python -m pytest src/test -q
.venv/bin/ruff check src scripts/check_desktop_imports.py docs/source/conf.py
.venv/bin/ruff format --check src scripts/check_desktop_imports.py docs/source/conf.py
python3 scripts/check_project.py .
python3 scripts/check_public_docstrings.py
```

Tests should isolate settings/cache storage from the operator's application data. Generated ANTLR parsers are excluded from lint/format; update grammars through the parser-generation workflow. For documentation changes, run `.venv/bin/sphinx-build -W -b html docs/source docs/build/html`.

`run/build-executable.sh` and `.ps1` package local desktop code. Retain dependency/startup import checks and CI frozen-executable smoke checks; the embedded FastMCP dependency chain must be tested before releasing installers. Preserve the tested Pydantic constraint when changing those dependencies.

## Run, build, and deploy

Executable operations live in `run/`; root command scripts are compatibility adapters. Shared ignored configuration is `run-build/.env`, documented by `run-build/.env.example`; `run/.env.example` links to the canonical example. Use `run/README.md` for operations. Exported environment overrides the file; explicit command flags override defaults. Desktop/web preferences remain in the existing application settings, and local API-key use does not require container configuration.

The default `run/build-push-image.sh` builds local source. Only the explicitly selected `run/build-push-pypi.sh` path installs the exact published `OPA_VERSION`; keep the build paths distinct. `OPA_VERSION` is a build input, not a container runtime setting. Forward only each container's launch variables. MCP uses `OPA_COMPARTMENT_DOMAIN_SEARCH_DEPTH`; depth 2 means root plus immediate children, independent of recursive policy loading.

Deployment manages the named Container Instance. Runtime/image changes use explicit delete/create replacement with downtime; configuration-only changes can reuse images without Docker builds. The Load Balancer, backends, NSG/networking, workload IAM, and OCIR repository are managed outside the deployment script.

Do not commit `run-build/.env`, `run/.env`, OCI credentials, generated deployment JSON/state, cache snapshots, or build artifacts.

## Branch releases

The GitHub remote is `github`; the stable base branch is `main`. The release workflow handles `main`, `develop`, and `feature/*`. Conventional Commit messages drive semantic-release: `feat:` selects a minor release, while `feat!:` or a `BREAKING CHANGE:` footer selects a major release. A branch name or manually edited package version alone does not select the next release version.

`scripts/prepare_release_version.cjs` converts release tags to Python-compatible versions and updates the project version in `pyproject.toml`. Feature prereleases attach desktop installers after build/startup checks; PyPI publishing remains restricted to `main`. Verify workflow results and generated release metadata after pushing. Keep semantic-release's generated release history intact.
