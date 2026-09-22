from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings
from app.errors import ApiError


KEY_VERSION = "fernet-v1"


def _fernet() -> Fernet:
    key = get_settings().erp_encryption_key
    if not key:
        raise ApiError(
            503,
            "ERP_ENCRYPTION_NOT_CONFIGURED",
            "A criptografia de credenciais ERP não está configurada.",
        )
    try:
        return Fernet(key.encode("utf-8"))
    except Exception as exc:
        raise ApiError(503, "ERP_ENCRYPTION_KEY_INVALID", "A chave de criptografia ERP é inválida.") from exc


def encrypt_secret(secret: str) -> str:
    if not secret.strip():
        raise ApiError(422, "ERP_SECRET_EMPTY", "A credencial ERP não pode ser vazia.")
    return _fernet().encrypt(secret.encode("utf-8")).decode("utf-8")


def decrypt_secret(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ApiError(503, "ERP_SECRET_UNREADABLE", "A credencial ERP não pôde ser decifrada.") from exc
