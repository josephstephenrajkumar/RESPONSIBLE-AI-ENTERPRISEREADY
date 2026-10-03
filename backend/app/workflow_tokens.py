"""Workflow app tokens: the credential a workflow app presents to the gateway.

A token is issued once per app (`rai_app_<random>`), returned to the caller a single
time and stored only as a SHA-256 hash. It is kept by Activepieces inside an encrypted
connection, so the browser and this database never hold the plaintext.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import Column, DateTime, String

from app.database import Base, SessionLocal, engine

TOKEN_PREFIX = 'rai_app_'


class WorkflowAppToken(Base):
    __tablename__ = 'workflow_app_tokens'

    token_hash = Column(String(64), primary_key=True)
    app_id = Column(String(40), nullable=False, index=True)
    tenant_id = Column(String(160), nullable=False, default='default')
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    revoked_at = Column(DateTime, nullable=True)


def ensure_table() -> None:
    WorkflowAppToken.__table__.create(bind=engine, checkfirst=True)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def issue_token(app_id: str, tenant_id: str) -> str:
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    with SessionLocal() as session:
        session.add(WorkflowAppToken(token_hash=hash_token(token), app_id=app_id, tenant_id=tenant_id))
        session.commit()
    return token


def revoke_tokens(app_id: str) -> int:
    with SessionLocal() as session:
        rows = session.query(WorkflowAppToken).filter_by(app_id=app_id, revoked_at=None).all()
        for row in rows:
            row.revoked_at = datetime.utcnow()
        session.commit()
        return len(rows)


def authenticate_app_token(token: str) -> Optional[Dict[str, Any]]:
    """Return {app_id, tenant_id} for a live token, or None."""
    if not token or not token.startswith(TOKEN_PREFIX):
        return None
    with SessionLocal() as session:
        row = session.get(WorkflowAppToken, hash_token(token))
        if row is None or row.revoked_at is not None:
            return None
        return {'app_id': row.app_id, 'tenant_id': row.tenant_id}
