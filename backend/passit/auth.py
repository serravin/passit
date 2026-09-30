import hashlib

import jwt
from fastapi import HTTPException, Request
from sqlalchemy import select

from .domain import utc
from .models import LoginSession, User, UserSettings, now


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def authenticate(request: Request, optional=False):
    app = request.app
    settings, db = app.state.settings, app.state.db
    if settings.mode == "demo":
        cookie = request.cookies.get("passit_session", "")
        with db.sessions() as s:
            session = s.get(LoginSession, digest(cookie)) if cookie else None
            if session and utc(session.expires_at) > now():
                return s.get(User, session.user_id)
    else:
        header = request.headers.get("authorization", "")
        if header.startswith("Bearer "):
            try:
                token = header[7:]
                key = app.state.jwks.get_signing_key_from_jwt(token).key
                claims = jwt.decode(token, key, algorithms=["RS256"], audience=settings.audience,
                                    issuer=settings.issuer, options={"require": ["exp", "iss", "sub", "aud"]})
            except (jwt.PyJWTError, ValueError):
                raise HTTPException(401, "Invalid sign-in token") from None
            with db.transaction() as s:
                user = s.scalar(select(User).where(User.issuer == claims["iss"], User.subject == claims["sub"]))
                if not user:
                    user = User(issuer=claims["iss"], subject=claims["sub"], name=str(claims.get("name", "Storyteller"))[:80])
                    s.add(user)
                    s.flush()
                    s.add(UserSettings(user_id=user.id))
                user.admin = user.subject in settings.admin_subjects
                return user
    if optional:
        return None
    raise HTTPException(401, "Sign in to continue")


def require_user(request: Request):
    return authenticate(request)


def optional_user(request: Request):
    return authenticate(request, optional=True)


def require_admin(request: Request):
    user = authenticate(request)
    if not user.admin:
        raise HTTPException(403, "Administrator access required")
    return user
