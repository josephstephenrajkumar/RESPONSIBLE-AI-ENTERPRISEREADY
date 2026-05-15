from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import httpx
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings

try:
    import jwt
    from jwt import PyJWKClient
except ImportError:  # pragma: no cover - keeps local fallback usable without auth extras.
    jwt = None
    PyJWKClient = None


security = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: str
    email: str
    username: str = ''
    tenant_id: str = 'default'
    groups: tuple[str, ...] = ()
    claims: dict[str, Any] | None = None


@lru_cache(maxsize=1)
def _jwk_client():
    if not Settings.COGNITO_ISSUER or PyJWKClient is None:
        return None
    return PyJWKClient(f'{Settings.COGNITO_ISSUER}/.well-known/jwks.json')


def _decode_cognito_token(token: str) -> dict[str, Any]:
    if jwt is None or PyJWKClient is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='PyJWT is required when AUTH_REQUIRED=true',
        )
    if not Settings.COGNITO_ISSUER or not Settings.COGNITO_APP_CLIENT_ID:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Cognito issuer and app client id must be configured',
        )

    try:
        signing_key = _jwk_client().get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=['RS256'],
            audience=Settings.COGNITO_APP_CLIENT_ID,
            issuer=Settings.COGNITO_ISSUER,
            options={'require': ['exp', 'iat', 'iss', 'sub']},
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f'Invalid authentication token: {exc}',
        ) from exc


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    x_tenant_id: str | None = Header(default=None, alias='X-Tenant-Id'),
) -> AuthenticatedUser:
    if not Settings.AUTH_REQUIRED:
        return AuthenticatedUser(
            user_id=Settings.LOCAL_DEV_USER_ID,
            email=Settings.LOCAL_DEV_USER_EMAIL,
            username='local-dev',
            tenant_id=x_tenant_id or 'local',
            groups=('admin',),
            claims={},
        )

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Authentication is required',
        )

    claims = _decode_cognito_token(credentials.credentials)
    groups = tuple(claims.get('cognito:groups', []) or [])
    return AuthenticatedUser(
        user_id=str(claims.get('sub', '')),
        email=str(claims.get('email', '')),
        username=str(claims.get('cognito:username', claims.get('username', ''))),
        tenant_id=x_tenant_id or str(claims.get('custom:tenant_id', 'default')),
        groups=groups,
        claims=claims,
    )


def user_can_manage_policies(user: AuthenticatedUser) -> bool:
    allowed_groups = {'admin', 'policy-manager', 'guardrails-admin'}
    return bool(allowed_groups.intersection(user.groups))


async def require_policy_manager(
    user: AuthenticatedUser = Depends(get_current_user),
) -> AuthenticatedUser:
    if not user_can_manage_policies(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail='Policy manager permission is required',
        )
    return user


def auth_runtime_config() -> dict[str, Any]:
    domain = Settings.COGNITO_DOMAIN.strip()
    if domain and not domain.startswith('http'):
        domain = f'https://{domain}'

    return {
        'auth_required': Settings.AUTH_REQUIRED,
        'token_storage_key': 'enterprise_auth_token',
        'cognito': {
            'region': Settings.COGNITO_REGION,
            'user_pool_id': Settings.COGNITO_USER_POOL_ID,
            'app_client_id': Settings.COGNITO_APP_CLIENT_ID,
            'issuer': Settings.COGNITO_ISSUER,
            'domain': domain,
            'scopes': ['openid', 'email', 'profile'],
            'response_type': 'code',
            'pkce': True,
        },
    }


async def check_cognito_metadata() -> dict[str, Any]:
    if not Settings.COGNITO_ISSUER:
        return {'configured': False, 'reason': 'COGNITO_ISSUER is not set'}
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(f'{Settings.COGNITO_ISSUER}/.well-known/openid-configuration')
        response.raise_for_status()
        metadata = response.json()
    return {
        'configured': True,
        'issuer': metadata.get('issuer'),
        'jwks_uri': metadata.get('jwks_uri'),
    }
