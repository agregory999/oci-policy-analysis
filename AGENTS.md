# Project context

Package code is under `src/oci_policy_analysis`; interfaces are desktop, CLI, FastAPI web, and FastMCP. Shared policy analysis lives under `application/`. Keep the published command names stable.

Use `uv sync --extra web --extra mcp` for local dependencies, `run/local.sh` for source running, and `run/README.md` for container operations. Prefer focused pytest modules and Ruff for changed Python. The default container build uses local source. The explicitly requested run/build-push-pypi.sh path installs only the pinned published OPA_VERSION; keep these build paths distinct. Do not commit `run/.env`, OCI credentials, generated deployment JSON, or build artifacts. The Load Balancer and NSG are managed outside this repository's deployment script.

Scripts live in `run/`; their shared ignored configuration is `run-build/.env`, documented by `run-build/.env.example`. Do not commit either local credentials or generated deployment state.
