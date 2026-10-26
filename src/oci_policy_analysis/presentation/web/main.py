"""FastAPI app entrypoint for the tiny web proof-of-concept."""

from __future__ import annotations

import argparse
import os
import secrets
import warnings
from importlib.resources import files

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

# Suppress OCI SDK datetime.utcnow() DeprecationWarning (Python 3.12+)
warnings.filterwarnings('ignore', category=DeprecationWarning, message=r'.*datetime\.datetime\.utcnow\(\).*')
# Suppress DeprecationWarnings from libraries
warnings.filterwarnings('ignore', category=DeprecationWarning)

from oci_policy_analysis.presentation.web.api.routes_core import router as core_router  # noqa: E402

STATIC_DIR = files('oci_policy_analysis.presentation.web').joinpath('static')

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
    """Serve the FastAPI application using command-line startup options.

    Raises:
        SystemExit: When argparse handles help or invalid startup arguments.

    Notes:
        Reads --host, --port, and --reload, with WEB_HOST/WEB_PORT defaults. Starts
        Uvicorn and blocks until shutdown. ASGI hosts can import the module's app
        directly; embedded analysis should use AppContext and application services.
    """

    parser = argparse.ArgumentParser(description='Run OCI Policy Analysis web server')
    parser.add_argument(
        '--host', default=os.environ.get('WEB_HOST', '127.0.0.1'), help='Bind host (default: 127.0.0.1)'
    )
    parser.add_argument(
        '--port', type=int, default=int(os.environ.get('WEB_PORT', '8000')), help='Bind port (default: 8000)'
    )
    parser.add_argument('--reload', action='store_true', help='Enable auto-reload (dev only)')
    args = parser.parse_args()

    uvicorn.run('oci_policy_analysis.presentation.web.main:app', host=args.host, port=args.port, reload=args.reload)


if __name__ == '__main__':
    main()
