from app.errors import ApiError


ALLOWED_REPRESENTATION_TRANSITIONS = {
    "PENDING": {"ACTIVE"},
    "ACTIVE": {"REVOKED"},
    "REVOKED": set(),
}


def require_representation_transition(
    current_status: str,
    target_status: str,
) -> None:
    allowed_targets = ALLOWED_REPRESENTATION_TRANSITIONS.get(
        current_status,
        set(),
    )
    if target_status in allowed_targets:
        return

    if target_status == "ACTIVE":
        raise ApiError(
            409,
            "REPRESENTATION_NOT_PENDING",
            "A autorização não está pendente.",
        )
    if target_status == "REVOKED":
        raise ApiError(
            409,
            "REPRESENTATION_NOT_ACTIVE",
            "A autorização não está ativa.",
        )
    raise ApiError(
        409,
        "REPRESENTATION_TRANSITION_INVALID",
        "A transição solicitada não é permitida.",
    )
