from collections.abc import Iterable

from app.errors import ApiError


REPRESENTATION_TO_GRANT_PERMISSION = {
    "VIEW_STATUS": "READ",
    "UPDATE_OPPORTUNITY": "UPDATE",
    "UPLOAD_DOCUMENTS": "UPLOAD_DOCUMENTS",
}


def derive_representation_grant_permissions(
    allowed_actions: Iterable[str],
) -> list[str]:
    permissions = {
        REPRESENTATION_TO_GRANT_PERMISSION[action]
        for action in allowed_actions
        if action in REPRESENTATION_TO_GRANT_PERMISSION
    }
    return sorted(permissions)


def require_representation_action(
    allowed_actions: Iterable[str],
    required_action: str,
) -> None:
    if required_action not in set(allowed_actions):
        raise ApiError(
            403,
            "REPRESENTATION_ACTION_NOT_ALLOWED",
            "A autorização não permite esta ação.",
        )
