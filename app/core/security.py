"""Security utilities (password hashing, JWT, and role checks).

This module is written to be usable both with and without FastAPI installed.
When FastAPI is available, `get_current_user` / `require_roles` return/raise
`HTTPException` as expected.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional, Sequence, Set, TypeVar

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings


# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


# Optional FastAPI integration
try:  # pragma: no cover
    from fastapi import Depends, HTTPException, status
    from fastapi.security import OAuth2PasswordBearer

    _FASTAPI = True
except Exception:  # pragma: no cover
    Depends = None  # type: ignore[assignment]
    OAuth2PasswordBearer = None  # type: ignore[assignment]
    HTTPException = None  # type: ignore[assignment]

    class _Status:
        HTTP_401_UNAUTHORIZED = 401
        HTTP_403_FORBIDDEN = 403

    status = _Status()  # type: ignore[assignment]
    _FASTAPI = False


class UnauthorizedError(Exception):
    """Raised when a request is not authenticated."""


class ForbiddenError(Exception):
    """Raised when a request is authenticated but not authorized."""


def _raise_unauthorized(detail: str = "Could not validate credentials") -> None:
    if _FASTAPI:
        raise HTTPException(  # type: ignore[misc]
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        )
    raise UnauthorizedError(detail)


def _raise_forbidden(detail: str = "Not enough permissions") -> None:
    if _FASTAPI:
        raise HTTPException(  # type: ignore[misc]
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail,
        )
    raise ForbiddenError(detail)


def create_access_token(data: dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token.

    `data` should include a `sub` claim (user id).
    """

    to_encode = dict(data)
    expire = datetime.now(timezone.utc) + (
        expires_delta
        if expires_delta is not None
        else timedelta(minutes=int(getattr(settings, "ACCESS_TOKEN_EXPIRE_MINUTES", 60)))
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def _extract_sub(payload: dict[str, Any]) -> str:
    sub = payload.get("sub")
    if sub is None:
        _raise_unauthorized("Token missing 'sub'")
    if not isinstance(sub, (str, int)):
        _raise_unauthorized("Invalid 'sub' in token")
    return str(sub)


def _get_user_roles(user: Any) -> Set[str]:
    roles: Set[str] = set()

    if user is None:
        return roles

    if isinstance(user, dict):
        raw_roles = user.get("roles")
        if isinstance(raw_roles, (list, tuple, set)):
            roles.update(str(r) for r in raw_roles if r)
        raw_role = user.get("role")
        if raw_role:
            roles.add(str(raw_role))
        if user.get("is_admin") is True or user.get("admin") is True:
            roles.add("admin")
        return roles

    # Object-like
    raw_roles = getattr(user, "roles", None)
    if isinstance(raw_roles, (list, tuple, set)):
        roles.update(str(r) for r in raw_roles if r)

    raw_role = getattr(user, "role", None)
    if raw_role:
        roles.add(str(raw_role))

    if getattr(user, "is_admin", False) is True or getattr(user, "admin", False) is True:
        roles.add("admin")

    return roles


def _lookup_user(db: Any, sub: str) -> Any:
    """Try to locate the user by id in a variety of backends.

    Supports:
    - pymongo-style: db.users.find_one({...})
    - repository-style: db.get_user(sub)
    - SQLAlchemy-style: db.query(User).filter(...).first()

    Returns the user object/document or None.
    """

    if db is None:
        return None

    # MongoDB style (this repo)
    users_coll = getattr(db, "users", None)
    if users_coll is not None and hasattr(users_coll, "find_one"):
        # Prefer numeric user_id
        try:
            uid_int = int(sub)
        except Exception:
            uid_int = None

        if uid_int is not None:
            doc = users_coll.find_one({"user_id": uid_int})
            if doc is not None:
                return doc

        # Try ObjectId if available
        try:
            from bson import ObjectId  # type: ignore

            if ObjectId.is_valid(sub):
                return users_coll.find_one({"_id": ObjectId(sub)})
        except Exception:
            pass

        # Fallback: string id
        return users_coll.find_one({"user_id": sub})

    # Repository style
    get_user = getattr(db, "get_user", None)
    if callable(get_user):
        try:
            return get_user(sub)
        except Exception:
            return None

    # SQLAlchemy style
    if hasattr(db, "query"):
        try:
            uid_int = int(sub)
        except Exception:
            uid_int = None

        if uid_int is None:
            return None

        User = None
        try:
            from app.models import User as _User  # type: ignore

            User = _User
        except Exception:
            try:
                from app.models.user import User as _User  # type: ignore

                User = _User
            except Exception:
                User = None

        if User is None:
            return None

        # Common field names
        if hasattr(User, "id"):
            return db.query(User).filter(User.id == uid_int).first()
        if hasattr(User, "user_id"):
            return db.query(User).filter(User.user_id == uid_int).first()

    return None


# OAuth2 bearer scheme (FastAPI only)
if _FASTAPI:  # pragma: no cover
    oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")  # type: ignore[misc]
else:
    oauth2_scheme = None


if _FASTAPI:  # pragma: no cover

    from functools import lru_cache

    @lru_cache(maxsize=1)
    def _get_db_manager() -> Any:
        # Prefer the repository's Mongo DatabaseManager singleton-ish instance.
        # It is safe in CI/docs mode (falls back to a no-op DB).
        from database.manager import DatabaseManager  # type: ignore

        return DatabaseManager()

    def get_db() -> Any:
        """FastAPI dependency: return a DB handle.

        Order of preference:
        1) `app.core.database.get_db` if the app defines it
        2) `webapp.app.get_db` (this repo's Flask Mongo accessor)
        3) `database.manager.DatabaseManager().db`
        """

        try:
            from app.core.database import get_db as _get_db  # type: ignore

            db = _get_db()
            if db is not None:
                return db
        except Exception:
            pass

        try:
            from webapp.app import get_db as _get_db  # type: ignore

            return _get_db()
        except Exception:
            pass

        try:
            return _get_db_manager().db
        except Exception:
            return None

    def get_current_user(token: str = Depends(oauth2_scheme), db: Any = Depends(get_db)) -> Any:  # type: ignore[misc]
        """FastAPI dependency: decode JWT, load user from DB."""

        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
            sub = _extract_sub(payload)
        except JWTError:
            _raise_unauthorized()

        user = _lookup_user(db, sub)
        if user is None:
            _raise_unauthorized("User not found")
        return user


else:

    def get_current_user(token: str, db: Any = None) -> Any:
        """Decode JWT, load user from DB.

        This version does not rely on FastAPI; call it directly.
        """

        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
            sub = _extract_sub(payload)
        except JWTError:
            _raise_unauthorized()

        user = _lookup_user(db, sub)
        if user is None:
            _raise_unauthorized("User not found")
        return user


TUser = TypeVar("TUser")


def require_roles(required_roles: Sequence[str]) -> Callable[..., Any]:
    """Return a dependency/checker that enforces user roles.

    - With FastAPI installed: returns a dependency function.
    - Without FastAPI: returns a function that accepts a `current_user` argument.
    """

    normalized = {str(r).strip() for r in required_roles if str(r).strip()}

    if _FASTAPI:  # pragma: no cover

        def _dep(current_user: Any = Depends(get_current_user)) -> Any:  # type: ignore[misc]
            roles = _get_user_roles(current_user)
            if normalized and roles.isdisjoint(normalized):
                _raise_forbidden()
            return current_user

        return _dep

    def _check(current_user: Any) -> Any:
        roles = _get_user_roles(current_user)
        if normalized and roles.isdisjoint(normalized):
            _raise_forbidden()
        return current_user

    return _check
