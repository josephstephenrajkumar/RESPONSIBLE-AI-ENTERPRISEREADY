from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import httpx
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings
from app import workflow_tokens

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
    # Default attribution for callers that are applications rather than people
    # (workflow apps): copied onto /chat requests that do not set client_id.
    client_id: str = ''


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
    # Workflow apps authenticate with a gateway-issued app token (rai_app_...), in every
    # environment. The identity is the app itself: its tenant, no admin groups.
    if credentials is not None and credentials.credentials.startswith(workflow_tokens.TOKEN_PREFIX):
        app = workflow_tokens.authenticate_app_token(credentials.credentials)
        if app is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Invalid workflow app token')
        return AuthenticatedUser(
            user_id=f"workflow-app:{app['app_id']}",
            email='',
            username='workflow-app',
            tenant_id=app['tenant_id'],
            groups=('workflow-app',),
            claims={'workflow_app_id': app['app_id']},
            client_id=f"workflow-app:{app['app_id']}",
        )

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


# Role model for the operational dashboards. Cognito groups map one-to-one:
#   finops  -> spend, budgets, unit economics (FinOps dashboard)
#   aiops   -> latency, errors, dependency health (AIOps dashboard)
# `admin` sees everything. Policy managers keep the responsible-AI dashboards
# only; cost and operations data is a separate concern with its own audience.
def user_can_view_finops(user: AuthenticatedUser) -> bool:
    allowed_groups = {'admin', 'finops', 'finance'}
    return bool(allowed_groups.intersection(user.groups))


def user_can_manage_models(user: AuthenticatedUser) -> bool:
    """Add/remove models and providers in the LiteLLM catalogue (cost-bearing)."""
    allowed_groups = {'admin', 'model-admin'}
    return bool(allowed_groups.intersection(user.groups))


def user_can_view_aiops(user: AuthenticatedUser) -> bool:
    allowed_groups = {'admin', 'aiops', 'sre', 'platform-ops'}
    return bool(allowed_groups.intersection(user.groups))


def user_can_manage_workflows(user: AuthenticatedUser) -> bool:
    """Create, publish and delete workflow apps on the Activepieces engine (cost-bearing)."""
    allowed_groups = {'admin', 'workflow-admin', 'model-admin'}
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


async def require_finops_viewer(
    user: AuthenticatedUser = Depends(get_current_user),
) -> AuthenticatedUser:
    if not user_can_view_finops(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail='FinOps permission is required',
        )
    return user


async def require_model_admin(
    user: AuthenticatedUser = Depends(get_current_user),
) -> AuthenticatedUser:
    if not user_can_manage_models(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail='Model administration permission is required',
        )
    return user


async def require_aiops_viewer(
    user: AuthenticatedUser = Depends(get_current_user),
) -> AuthenticatedUser:
    if not user_can_view_aiops(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail='AIOps permission is required',
        )
    return user


async def require_workflow_admin(
    user: AuthenticatedUser = Depends(get_current_user),
) -> AuthenticatedUser:
    if not user_can_manage_workflows(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail='Workflow administration permission is required',
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
