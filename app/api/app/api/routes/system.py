"""System routes: health (root and under the API prefix), public policy, the caller's identity, and the site overview."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app import __version__
from app.api.deps import get_container
from app.auth.validator import Principal, require_auditor
from app.container import Container

health_router = APIRouter(tags=["system"])
public_router = APIRouter(tags=["system"])
router = APIRouter(tags=["system"], dependencies=[Depends(require_auditor)])


def _health_payload() -> dict[str, Any]:
    return {"status": "ok", "service": "sp-acl-api", "version": __version__}


@health_router.get("/health", summary="Liveness probe for App Service (no token)")
def root_health() -> dict[str, Any]:
    return _health_payload()


@public_router.get("/health", summary="Liveness and configuration status (no token)")
def health() -> dict[str, Any]:
    return _health_payload()


@public_router.get("/policy", summary="Governance labels, hygiene definitions and policy thresholds")
def policy(container: Container = Depends(get_container)) -> dict[str, Any]:
    governance = container.settings.governance
    labels = {group: governance.labels(group) for group in governance.vocabulary["labels"]}
    similarity = governance.similarity
    return {
        "labels": labels,
        "columns": governance.column_names(),
        "hygiene": {"metrics": governance.metrics, "findings": governance.findings},
        "eligibility": governance.eligibility,
        "similarity": {
            "nearDuplicateCosine": similarity["nearDuplicateCosine"],
            "conflictCandidateCosine": similarity["conflictCandidateCosine"],
            "embeddingCharacterLimit": similarity["embeddingCharacterLimit"],
            "note": similarity.get("note"),
        },
        "trustScore": {
            "minScore": governance.policy["trustScore"]["minScore"],
            "maxScore": governance.policy["trustScore"]["maxScore"],
            "weights": governance.trust_weights,
            "penalties": governance.trust_penalties,
        },
    }


@router.get("/me", summary="The signed-in auditor and the roles on the token")
def me(principal: Principal = Depends(require_auditor)) -> dict[str, Any]:
    return {
        "userPrincipalName": principal.upn,
        "name": principal.name,
        "objectId": principal.subject,
        "tenantId": principal.tenant_id,
        "applicationId": principal.app_id,
        "roles": list(principal.roles),
    }


@router.get("/site", summary="Site name, URL and configured library count")
def site(container: Container = Depends(get_container)) -> dict[str, Any]:
    return container.sites.info()
