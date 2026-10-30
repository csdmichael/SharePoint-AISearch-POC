"""ASGI entry point for gunicorn (App Service). API_CONFIG_PATH is relative to the package root, not the working directory."""

import os
from pathlib import Path

from app.core.config import load_settings, resolve_path
from app.factory import create_app

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
app = create_app(load_settings(resolve_path(PACKAGE_ROOT, os.environ.get("API_CONFIG_PATH", "config/api.config.json"))),
                 warm=True)
