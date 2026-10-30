"""Application factory: CORS, documentation routes, error envelope and the route modules."""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Callable, Mapping

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.errors import register_error_handlers
from app.api.routes import access, agent, analytics, documents, hygiene, notifications, sites, system
from app.container_manager import ContainerManager
from app.core.config import Settings
from app.services.warmer import CacheWarmer


def create_app(
    settings: Settings,
    *,
    transport: httpx.BaseTransport | None = None,
    credential: Any = None,
    environ: Mapping[str, str] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    warm: bool = False,
) -> FastAPI:
    container_manager = ContainerManager(
        settings,
        transport=transport,
        credential=credential,
        environ=environ,
        sleep=sleep,
    )
    container = container_manager.default_container
    interval = settings.api.cache.warmIntervalSeconds
    warmer = CacheWarmer(container_manager, interval_seconds=interval) if warm and interval > 0 else None

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if warmer is not None:
            warmer.start()
        try:
            yield
        finally:
            if warmer is not None:
                warmer.stop()
            container_manager.close()

    api = settings.api
    app = FastAPI(
        title=api.openapi.title,
        version=__version__,
        description=api.openapi.description,
        docs_url=api.docsPath,
        redoc_url=api.redocPath,
        openapi_url=api.openapiPath,
        lifespan=lifespan,
    )
    app.state.container = container
    app.state.container_manager = container_manager
    app.add_middleware(
        CORSMiddleware,
        allow_origins=api.cors.allowedOrigins,
        allow_methods=api.cors.allowedMethods,
        allow_headers=api.cors.allowedHeaders,
        allow_credentials=False,
    )
    register_error_handlers(app)

    prefix = api.routePrefix.rstrip("/")
    app.include_router(system.health_router)
    app.include_router(system.public_router, prefix=prefix)
    app.include_router(system.router, prefix=prefix)
    app.include_router(sites.router, prefix=prefix)
    app.include_router(access.router, prefix=prefix)
    app.include_router(documents.router, prefix=prefix)
    app.include_router(analytics.router, prefix=prefix)
    app.include_router(hygiene.router, prefix=prefix)
    app.include_router(notifications.router, prefix=prefix)
    app.include_router(agent.router, prefix=prefix)
    return app
