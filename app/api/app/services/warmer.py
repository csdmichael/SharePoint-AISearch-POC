"""Background cache warmer. On an interval shorter than the library cache TTL it rebuilds every configured site's
library corpora and hygiene model, so dashboard and analytics requests read memory instead of waiting on SharePoint
and Microsoft Graph. Extracted text is cached per content tag, so each pass downloads only files that changed.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from app.container_manager import ContainerManager

logger = logging.getLogger("sp_acl_api")
MIN_PASS_SECONDS = 5.0


class CacheWarmer:
    def __init__(
        self,
        manager: ContainerManager,
        *,
        interval_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._manager = manager
        self._interval = interval_seconds
        self._clock = clock
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="cache-warmer", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def warm_once(self) -> dict[str, str]:
        """Refreshes every site once and returns the outcome per site. A failed site is retried on the next pass."""

        outcomes: dict[str, str] = {}
        for site_id in self._manager.site_ids():
            if self._stop.is_set():
                break
            try:
                container = self._manager.for_site(site_id)
                for library in container.libraries.configured():
                    container.libraries.corpus(library.id, fresh=True)
                container.hygiene.refresh()
                outcomes[site_id] = "ok"
            except Exception as exc:  # warming is best effort; requests still build caches on demand
                logger.warning("Cache warm-up failed for site %s: %s", site_id, exc)
                outcomes[site_id] = type(exc).__name__
        return outcomes

    def _run(self) -> None:
        while not self._stop.is_set():
            started = self._clock()
            self.warm_once()
            remaining = self._interval - (self._clock() - started)
            self._stop.wait(max(MIN_PASS_SECONDS, remaining))
