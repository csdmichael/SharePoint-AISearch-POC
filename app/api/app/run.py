"""Command-line entry point: python -m app.run --config config\\api.config.json"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import uvicorn

from app.core.config import ConfigError, load_settings
from app.factory import create_app

DEFAULT_CONFIG = Path("config") / "api.config.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the SharePoint governance API.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Path to api.config.json")
    args = parser.parse_args(argv)
    try:
        settings = load_settings(args.config)
    except ConfigError as exc:
        print(f"Configuration error. The API did not start.\n{exc}", file=sys.stderr)
        return 2
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if settings.applied_overrides:
        logging.getLogger("sp_acl_api").info(
            "Applied environment overrides: %s", ", ".join(settings.applied_overrides)
        )
    app = create_app(settings)
    uvicorn.run(app, host=settings.api.server.host, port=settings.api.server.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
