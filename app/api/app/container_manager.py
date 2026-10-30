"""Site-aware container cache so one API host can serve multiple allowed SharePoint sites."""

from __future__ import annotations

from dataclasses import replace
from threading import RLock
from typing import Any, Callable, Mapping

import httpx

from app.container import Container
from app.core.config import Settings
from app.core.errors import BadRequestError


class ContainerManager:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
        credential: Any = None,
        environ: Mapping[str, str] | None = None,
        sleep: Callable[[float], None],
    ) -> None:
        self._settings = settings
        self._transport = transport
        self._credential = credential
        self._environ = environ
        self._sleep = sleep
        self._lock = RLock()
        self._containers: dict[str, Container] = {}
        self._by_id = {site.site_id: site for site in settings.site_catalog}
        self._by_url = {site.site_url: site for site in settings.site_catalog}

    @property
    def default_container(self) -> Container:
        return self.for_site(None)

    def for_site(self, selector: str | None) -> Container:
        target = self._resolve_site(selector)
        with self._lock:
            hit = self._containers.get(target.site_id)
            if hit is not None:
                return hit
            scoped_settings = replace(self._settings, site=target)
            container = Container(
                scoped_settings,
                transport=self._transport,
                credential=self._credential,
                environ=self._environ,
                sleep=self._sleep,
            )
            self._containers[target.site_id] = container
            return container

    def site_ids(self) -> list[str]:
        return [site.site_id for site in self._settings.site_catalog]

    def _resolve_site(self, selector: str | None):
        if selector is None or not selector.strip():
            return self._settings.site
        key = selector.strip().lower()
        if key in self._by_id:
            return self._by_id[key]
        if selector.strip() in self._by_url:
            return self._by_url[selector.strip()]
        raise BadRequestError("site must match a configured site id.")

    def close(self) -> None:
        with self._lock:
            containers = list(self._containers.values())
            self._containers.clear()
        for container in containers:
            container.close()
