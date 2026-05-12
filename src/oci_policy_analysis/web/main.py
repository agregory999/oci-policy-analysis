"""FastAPI app entrypoint for the tiny web proof-of-concept."""

from __future__ import annotations

import argparse
import secrets
from importlib.resources import files

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from oci_policy_analysis.web.api.routes_core import router as core_router

STATIC_DIR = files('oci_policy_analysis.web').joinpath('static')

app = FastAPI(title='OCI Policy Analysis (POC)')

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)
app.add_middleware(SessionMiddleware, secret_key=secrets.token_urlsafe(32), same_site='lax', https_only=False)

app.include_router(core_router)
app.mount('/', StaticFiles(directory=str(STATIC_DIR), html=True), name='static')


def main() -> None:
    """Run the web app via CLI-friendly options."""

    parser = argparse.ArgumentParser(description='Run OCI Policy Analysis web server')
    parser.add_argument('--host', default='127.0.0.1', help='Bind host (default: 127.0.0.1)')
    parser.add_argument('--port', type=int, default=8000, help='Bind port (default: 8000)')
    parser.add_argument('--reload', action='store_true', help='Enable auto-reload (dev only)')
    args = parser.parse_args()

    uvicorn.run('oci_policy_analysis.web.main:app', host=args.host, port=args.port, reload=args.reload)


if __name__ == '__main__':
    main()
