import secrets

from fastapi import Header, HTTPException

from app.config import get_settings


def require_admin_secret(x_admin_secret: str | None = Header(default=None)) -> None:
    expected = get_settings().admin_api_secret
    if not expected or not x_admin_secret or not secrets.compare_digest(x_admin_secret, expected):
        raise HTTPException(status_code=401, detail="Admin authentication required")
