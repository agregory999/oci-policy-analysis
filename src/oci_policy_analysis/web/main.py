"""FastAPI app entrypoint for the tiny web proof-of-concept."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from oci_policy_analysis.web.api.routes_core import router as core_router

app = FastAPI(title='OCI Policy Analysis (POC)')

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

app.include_router(core_router)
app.mount('/', StaticFiles(directory='src/oci_policy_analysis/web/static', html=True), name='static')


def main() -> None:
    """Placeholder runner for CLI invocation.

    Use `uvicorn oci_policy_analysis.web.main:app --reload` for dev.
    """

    import uvicorn

    uvicorn.run('oci_policy_analysis.web.main:app', host='127.0.0.1', port=8000, reload=True)


if __name__ == '__main__':
    main()
