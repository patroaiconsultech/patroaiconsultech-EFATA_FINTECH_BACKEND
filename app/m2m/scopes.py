from __future__ import annotations

from dataclasses import dataclass


M2M_CONTRACT_VERSION = "m2m-r1"
M2M_API_VERSION = "v1"


@dataclass(frozen=True)
class M2MCapability:
    scope: str
    method: str
    path: str
    nature: str
    tenant_required: bool = True
    write: bool = False


R1_CAPABILITIES: tuple[M2MCapability, ...] = (
    M2MCapability(
        scope="fintech.health.read",
        method="GET",
        path="/api/v1/m2m/health",
        nature="operational",
    ),
    M2MCapability(
        scope="fintech.runtime.read",
        method="GET",
        path="/api/v1/m2m/runtime",
        nature="operational",
    ),
    M2MCapability(
        scope="fintech.capabilities.read",
        method="GET",
        path="/api/v1/m2m/capabilities",
        nature="contract",
    ),
    M2MCapability(
        scope="fintech.audit.read",
        method="GET",
        path="/api/v1/m2m/audit/events",
        nature="audit",
    ),
)

R1_SCOPE_SET = frozenset(item.scope for item in R1_CAPABILITIES)


def get_capability(scope: str) -> M2MCapability | None:
    return next((item for item in R1_CAPABILITIES if item.scope == scope), None)
