"""Authentication and Role-Based Access Control (RBAC) middleware and dependencies."""

from __future__ import annotations

import secrets
from typing import Callable, List, Optional
from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader, HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

from apps.api.config import config

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
bearer_auth = HTTPBearer(auto_error=False)


class UserContext(BaseModel):
    """Authenticated user/service principal identity."""

    principal_id: str
    role: str  # admin, operator, viewer
    scopes: List[str] = []


ROLE_HIERARCHY = {
    "admin": 3,
    "operator": 2,
    "viewer": 1,
}


def _matches_any_key(candidate: str, allowed_keys: list[str]) -> bool:
    """Constant-time comparison against configured key list to prevent timing attacks."""
    return any(secrets.compare_digest(candidate, k) for k in allowed_keys)


async def get_current_user(
    api_key: Optional[str] = Security(api_key_header),
    token: Optional[HTTPAuthorizationCredentials] = Security(bearer_auth),
) -> UserContext:
    """Validate identity from API key or Bearer token."""
    key = api_key or (token.credentials if token else None)

    if not key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication credentials. Provide X-API-Key or Bearer token.",
            headers={"WWW-Authenticate": "ApiKey, Bearer"},
        )

    # Validate against configured keys using constant-time comparison
    if _matches_any_key(key, config.admin_api_keys):
        return UserContext(principal_id="admin-user", role="admin", scopes=["*"])
    elif _matches_any_key(key, config.operator_api_keys):
        return UserContext(principal_id="operator-user", role="operator", scopes=["read", "write", "execute"])
    elif _matches_any_key(key, config.viewer_api_keys):
        return UserContext(principal_id="viewer-user", role="viewer", scopes=["read"])

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication credentials.",
        headers={"WWW-Authenticate": "ApiKey, Bearer"},
    )


def require_role(minimum_role: str) -> Callable[[UserContext], UserContext]:
    """Dependency factory enforcing minimum required RBAC role."""

    def role_checker(user: UserContext = Security(get_current_user)) -> UserContext:
        user_level = ROLE_HIERARCHY.get(user.role, 0)
        required_level = ROLE_HIERARCHY.get(minimum_role, 0)
        if user_level < required_level:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required role: '{minimum_role}', user role: '{user.role}'",
            )
        return user

    return role_checker
