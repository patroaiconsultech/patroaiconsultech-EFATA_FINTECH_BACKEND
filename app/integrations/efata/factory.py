from app.config import Settings
from app.errors import ApiError
from app.integrations.efata.mock import MockEfataAdapter
from app.integrations.efata.port import FintechEfataPort


def get_efata_adapter(settings: Settings) -> FintechEfataPort:
    if settings.efata_mode == "mock":
        return MockEfataAdapter()

    # R4 intentionally has no real platform adapter.
    raise ApiError(
        503,
        "EFATA_REAL_INTEGRATION_DISABLED",
        "A integração real com a Plataforma Efatà não está habilitada.",
    )
