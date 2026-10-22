"""Composition root: builds the HTTP clients, caches and services from the validated settings."""

from __future__ import annotations

import os
import re
import time
from typing import Any, Callable, Mapping

import httpx

from app.agent.foundry import FoundryClient
from app.agent.handlers import HandlerContext
from app.agent.router import IntentRouter
from app.agent.service import AgentService, Caller
from app.auth.validator import JwksCache, TokenValidator
from app.clients.graph import GraphClient
from app.clients.sharepoint import SharePointClient
from app.clients.transport import TokenProvider, UpstreamHttp, build_credential
from app.core.config import Settings
from app.domain.principals import PrincipalClassifier
from app.services.access import AccessService
from app.services.analytics import AnalyticsService
from app.services.documents import DocumentService
from app.services.exposure import ExposureService
from app.services.hygiene import HygieneService
from app.services.library import LibraryService
from app.services.membership import MembershipService
from app.services.notifications import NotificationService, OutboxStore
from app.services.sites import SiteService


class Container:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
        credential: Any = None,
        environ: Mapping[str, str] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings
        api = settings.api
        identity = api.identity
        graph_config = api.graph
        site = settings.site
        analytics_config = settings.analytics
        governance = settings.governance
        environment = os.environ if environ is None else environ

        self.credential = credential if credential is not None else build_credential(identity, environment)
        margin = identity.tokenRefreshMarginSeconds
        graph_tokens = TokenProvider(self.credential, identity.graphScope, refresh_margin_seconds=margin)
        sharepoint_scope = identity.sharePointScopeTemplate.replace("{sharePointHost}", site.host)
        sharepoint_tokens = TokenProvider(self.credential, sharepoint_scope, refresh_margin_seconds=margin)

        self._graph_http = UpstreamHttp(
            "Microsoft Graph", graph_config.baseUrl, transport=transport,
            timeout_seconds=graph_config.timeoutSeconds, max_retries=graph_config.maxRetries,
            backoff_seconds=graph_config.retryBackoffSeconds, max_delay_seconds=graph_config.maxRetryDelaySeconds,
            sleep=sleep,
        )
        self._sharepoint_http = UpstreamHttp(
            "SharePoint", site.site_url, transport=transport,
            timeout_seconds=graph_config.timeoutSeconds, max_retries=graph_config.maxRetries,
            backoff_seconds=graph_config.retryBackoffSeconds, max_delay_seconds=graph_config.maxRetryDelaySeconds,
            sleep=sleep,
        )
        self.sharepoint = SharePointClient(
            site.site_url, http=self._sharepoint_http, tokens=sharepoint_tokens, page_size=api.sharePoint.pageSize
        )
        self.graph = GraphClient(graph_config.baseUrl, http=self._graph_http, tokens=graph_tokens,
                                 page_size=graph_config.pageSize)

        self._jwks_http = httpx.Client(transport=transport, timeout=httpx.Timeout(graph_config.timeoutSeconds))
        jwks_url = f"{api.auth.authorityHostUrl.rstrip('/')}/{site.tenant_id}{api.auth.jwksPath}"
        self.jwks = JwksCache(
            jwks_url,
            client=self._jwks_http,
            cache_seconds=api.auth.jwksCacheSeconds,
            min_refresh_seconds=api.auth.jwksMinRefreshSeconds,
            clock=clock,
        )
        self.validator = TokenValidator(api.auth, site.tenant_id, jwks=self.jwks)

        exposure_config = analytics_config.exposure
        self.classifier = PrincipalClassifier(
            analytics_config.loginNamePatterns,
            everyone_including_external=exposure_config.everyoneLoginPattern,
            type_map=api.sharePoint.principalTypes,
            claim_labels=exposure_config.everyoneLabels,
        )
        user_pattern = re.compile(analytics_config.loginNamePatterns.user, re.IGNORECASE)
        self.membership = MembershipService(
            graph=self.graph,
            sharepoint=self.sharepoint,
            user_pattern=user_pattern,
            ttl_seconds=api.cache.membershipTtlSeconds,
            max_members=graph_config.maxMembersPerGroup,
            clock=clock,
        )
        self.libraries = LibraryService(
            settings=settings,
            governance=governance,
            sharepoint=self.sharepoint,
            graph=self.graph,
            classifier=self.classifier,
            clock=clock,
        )
        self.exposure = ExposureService(settings=settings, membership=self.membership)
        self.analytics = AnalyticsService(settings=settings, governance=governance, exposure=self.exposure)
        self.sites = SiteService(
            settings=settings,
            sharepoint=self.sharepoint,
            libraries=self.libraries,
            membership=self.membership,
            origin=self.libraries.origin,
        )
        self.access = AccessService(
            settings=settings,
            sharepoint=self.sharepoint,
            libraries=self.libraries,
            membership=self.membership,
            user_pattern=user_pattern,
            external_pattern=re.compile(exposure_config.externalUserPattern, re.IGNORECASE),
        )
        self.documents = DocumentService(
            settings=settings, governance=governance, libraries=self.libraries, analytics=self.analytics
        )
        self.hygiene = HygieneService(
            settings=settings, governance=governance, libraries=self.libraries, analytics=self.analytics
        )
        self.outbox = OutboxStore(settings.outbox_path)
        self.notifications = NotificationService(
            settings=settings,
            governance=governance,
            graph=self.graph,
            libraries=self.libraries,
            hygiene=self.hygiene,
            store=self.outbox,
        )

        foundry_target = settings.foundry
        self.foundry: FoundryClient | None = None
        if foundry_target.configured:
            self.foundry = FoundryClient(
                foundry_target,
                tokens=TokenProvider(self.credential, foundry_target.token_scope, refresh_margin_seconds=margin),
                max_retry_delay_seconds=graph_config.maxRetryDelaySeconds,
                transport=transport,
                sleep=sleep,
            )
        self.agent = AgentService(
            agent=settings.agent,
            prompts=settings.prompts,
            router=IntentRouter(settings.agent.intents, settings.agent.fallbackIntent),
            context_for=self._agent_context,
            foundry=self.foundry,
        )

    def _agent_context(self, caller: Caller) -> HandlerContext:
        agent = self.settings.agent
        exposure = self.settings.analytics.exposure
        labels = {
            "everyoneIncludingExternal": exposure.everyoneLabels["includingExternal"],
            "everyoneExceptExternal": exposure.everyoneLabels["exceptExternal"],
            "anonymousLink": exposure.linkLabels["anonymous"],
            "organizationLink": exposure.linkLabels["organization"],
        }
        return HandlerContext(
            libraries=self.libraries,
            analytics=self.analytics,
            access=self.access,
            hygiene=self.hygiene,
            notifications=self.notifications,
            exposure_labels=labels,
            evidence_limit=agent.evidenceLimit,
            limits=agent.limits,
            answers=agent.answers,
            finding_ids=agent.findingIds,
            draft=agent.draftNotification,
            prompts=[prompt.model_dump() for prompt in self.settings.prompts.prompts],
            caller_upn=caller.upn,
            caller_name=caller.name,
            signed_in_user=agent.messages.signedInUser,
        )

    def close(self) -> None:
        for client in (self._graph_http, self._sharepoint_http):
            client.close()
        self._jwks_http.close()
        if self.foundry is not None:
            self.foundry.close()
