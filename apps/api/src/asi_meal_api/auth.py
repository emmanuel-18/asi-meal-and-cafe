"""Local password authentication and persistent opaque sessions. No global DB."""

import base64
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import secrets

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from sqlalchemy import func, or_, select, text, update
from sqlalchemy.orm import Session

from asi_meal_api.db import models as m
from asi_meal_api.orders import ActorContext, Forbidden


class AuthenticationFailed(ValueError):
    def __init__(self):
        super().__init__("Authentication failed")


class CSRFRejected(ValueError):
    pass


class ProvisioningRejected(ValueError):
    pass


def encode_token(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def decode_token(value: str | None) -> bytes:
    try:
        if not isinstance(value, str) or len(value) != 43:
            raise ValueError
        raw = base64.b64decode(value + "=", altchars=b"-_", validate=True)
        if len(raw) != 32 or encode_token(raw) != value:
            raise ValueError
        return raw
    except (ValueError, UnicodeError):
        raise AuthenticationFailed() from None


class Passwords:
    def __init__(self):
        # Explicit Argon2id parameters: 64 MiB, three iterations, one lane.
        self.hasher = PasswordHasher(memory_cost=65536, time_cost=3, parallelism=1, type=Type.ID)
        # Comparable work for unknown/invalid hashes; not an account or credential.
        self._dummy = self.hasher.hash(secrets.token_urlsafe(32))

    @staticmethod
    def valid_input(password: str) -> bool:
        try:
            return (isinstance(password, str) and len(password) >= 8 and bool(password.strip())
                    and len(password.encode("utf-8")) <= 1024)
        except UnicodeError:
            return False

    def hash(self, password: str) -> str:
        if not self.valid_input(password):
            raise ProvisioningRejected("Password must be nonblank, contain at least 8 characters, and use at most 1024 UTF-8 bytes")
        return self.hasher.hash(password)

    def verify(self, encoded: str | None, password: str) -> bool:
        if not self.valid_input(password):
            return False
        supported = isinstance(encoded, str) and encoded.startswith("$argon2id$")
        try:
            valid = self.hasher.verify(encoded if supported else self._dummy, password)
            return bool(valid and supported)
        except VerifyMismatchError:
            return False
        except (InvalidHashError, VerificationError):
            self._dummy_verify(password)
            return False

    def _dummy_verify(self, password):
        try:
            self.hasher.verify(self._dummy, password)
        except VerificationError:
            pass


@dataclass(frozen=True, slots=True)
class Identity:
    id: int
    login_name: str
    display_name: str
    role: str
    password_change_required: bool = False

    @property
    def actor(self) -> ActorContext:
        return ActorContext(self.id)


@dataclass(frozen=True, slots=True)
class SessionResult:
    user: Identity
    token: str = field(repr=False)
    csrf_token: str = field(repr=False)
    expires_at: datetime


class AuthService:
    def __init__(self, session_factory: Callable[[], Session], *, passwords: Passwords | None = None,
                 lifetime: timedelta = timedelta(hours=8), idle_timeout: timedelta = timedelta(minutes=30),
                 clock: Callable[[], datetime] | None = None):
        if not timedelta(0) < idle_timeout <= lifetime <= timedelta(hours=8):
            raise ValueError("Invalid session lifetime configuration")
        self._sessions = session_factory
        self.passwords = passwords or Passwords()
        self.lifetime = lifetime
        self.idle_timeout = idle_timeout
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @property
    def session_factory(self) -> Callable[[], Session]:
        """Compose business services with independent transactions on the same database."""
        return self._sessions

    @staticmethod
    def _identity(user: m.User) -> Identity:
        return Identity(user.id, user.login_name, user.display_name, user.role_code, user.password_change_required)

    @staticmethod
    def _digest(token: str | None) -> bytes:
        return hashlib.sha256(decode_token(token)).digest()

    @staticmethod
    def _audit(session, user_id, action, after):
        session.add(m.AuditEvent(actor_user_id=user_id, action=action, entity_type="users", entity_key=str(user_id),
                                before_values=None, after_values=after, reason="Local authentication"))

    def login(self, login_name: str, password: str, previous_token: str | None = None) -> SessionResult:
        if not isinstance(login_name, str) or not 0 < len(login_name) <= 255 or not self.passwords.valid_input(password):
            raise AuthenticationFailed()
        try:
            old_digest = self._digest(previous_token)
        except AuthenticationFailed:
            old_digest = None
        with self._sessions() as session, session.begin():
            user_id = session.scalar(select(m.User.id).where(func.lower(func.btrim(m.User.login_name)) == func.lower(func.btrim(login_name))))
            old_id = session.scalar(select(m.AuthSession.user_id).where(m.AuthSession.token_hash == old_digest)) if old_digest else None
            # Consistent user-before-session order, including switching accounts.
            ids = sorted({i for i in (user_id, old_id) if i is not None})
            users = {u.id: u for u in session.scalars(select(m.User).where(m.User.id.in_(ids)).order_by(m.User.id).with_for_update())}
            user = users.get(user_id)
            valid = self.passwords.verify(user.password_hash if user else None, password)
            if not valid or user is None or not user.is_enabled or user.role_code not in {"admin", "assistant_admin", "super_admin"}:
                raise AuthenticationFailed()
            now = self._clock()
            if old_digest:
                old = session.scalar(select(m.AuthSession).where(m.AuthSession.token_hash == old_digest).with_for_update())
                if old is not None and old.revoked_at is None:
                    old.revoked_at = max(now, old.created_at)
            if self.passwords.hasher.check_needs_rehash(user.password_hash):
                user.password_hash = self.passwords.hasher.hash(password)
                user.updated_at = now
            raw = secrets.token_bytes(32)
            csrf = secrets.token_bytes(32)
            auth = m.AuthSession(user_id=user.id, token_hash=hashlib.sha256(raw).digest(), csrf_token=csrf,
                                 created_at=now, last_seen_at=now, expires_at=now + self.lifetime)
            session.add(auth)
            session.flush()
            self._audit(session, user.id, "auth_login", {"session_id": auth.id})
            return SessionResult(self._identity(user), encode_token(raw), encode_token(csrf), auth.expires_at)

    def _active(self, session, token, *, write_user=False):
        digest = self._digest(token)
        user_id = session.scalar(select(m.AuthSession.user_id).where(m.AuthSession.token_hash == digest))
        if user_id is None:
            raise AuthenticationFailed()
        user = session.scalar(select(m.User).where(m.User.id == user_id).with_for_update(read=not write_user))
        auth = session.scalar(select(m.AuthSession).where(m.AuthSession.token_hash == digest).with_for_update())
        now = self._clock()
        if (auth is None or user is None or not user.is_enabled or user.role_code not in {"admin", "assistant_admin", "super_admin"}
                or auth.revoked_at is not None or now >= auth.expires_at or now - auth.last_seen_at >= self.idle_timeout):
            raise AuthenticationFailed()
        return user, auth, max(now, auth.last_seen_at)

    @staticmethod
    def _check_csrf(auth, csrf_token):
        try:
            supplied = decode_token(csrf_token)
        except AuthenticationFailed:
            raise CSRFRejected("Request rejected") from None
        if not hmac.compare_digest(auth.csrf_token, supplied):
            raise CSRFRejected("Request rejected")

    def current(self, token: str | None, csrf_token: str | None = None, *, verify_csrf: bool = False) -> SessionResult:
        with self._sessions() as session, session.begin():
            user, auth, now = self._active(session, token)
            if verify_csrf:
                self._check_csrf(auth, csrf_token)
            auth.last_seen_at = now
            return SessionResult(self._identity(user), token, encode_token(auth.csrf_token), auth.expires_at)

    def logout(self, token: str | None, csrf_token: str | None) -> None:
        with self._sessions() as session, session.begin():
            user, auth, now = self._active(session, token)
            self._check_csrf(auth, csrf_token)
            auth.revoked_at = now
            self._audit(session, user.id, "auth_logout", {"session_id": auth.id})

    def change_password(self, token: str | None, csrf_token: str | None, current: str, new: str) -> SessionResult:
        encoded = self.passwords.hash(new)
        with self._sessions() as session, session.begin():
            user, auth, now = self._active(session, token, write_user=True)
            self._check_csrf(auth, csrf_token)
            if not self.passwords.verify(user.password_hash, current):
                raise AuthenticationFailed()
            if current == new:
                raise ProvisioningRejected("New password must differ from the current password")
            user.password_hash = encoded
            user.password_change_required = False
            user.updated_at = max(now, user.updated_at + timedelta(microseconds=1))
            session.execute(update(m.AuthSession).where(m.AuthSession.user_id == user.id,
                m.AuthSession.id != auth.id, m.AuthSession.revoked_at.is_(None)).values(revoked_at=func.greatest(now, m.AuthSession.created_at)))
            self._audit(session, user.id, "password_changed", {"password_change_required": False})
            return SessionResult(self._identity(user), token, encode_token(auth.csrf_token), auth.expires_at)

    def provision_first_admin(self, login_name: str, display_name: str, password: str) -> Identity:
        if (not isinstance(login_name, str) or not login_name.strip() or len(login_name) > 255
                or not isinstance(display_name, str) or not display_name.strip() or len(display_name) > 255):
            raise ProvisioningRejected("Nonblank login and display names of at most 255 characters are required")
        encoded = self.passwords.hash(password)
        with self._sessions() as session, session.begin():
            session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": int.from_bytes(b"ASIADMIN", "big")})
            if session.scalar(select(m.User.id).where(m.User.role_code == "admin").limit(1)) is not None:
                raise ProvisioningRejected("An Admin already exists; initial provisioning is refused")
            user = m.User(login_name=login_name.strip(" "), display_name=display_name.strip(), password_hash=encoded,
                          role_code="admin", is_enabled=True)
            session.add(user)
            session.flush()
            self._audit(session, user.id, "first_admin_provisioned", {"role": "admin", "source": "local_bootstrap"})
            return self._identity(user)

    def cleanup(self, limit: int = 1000) -> int:
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("Cleanup batch must be between 1 and 1000")
        with self._sessions() as session, session.begin():
            rows = session.scalars(select(m.AuthSession).where(or_(m.AuthSession.expires_at <= self._clock(),
                m.AuthSession.revoked_at.is_not(None))).order_by(m.AuthSession.id).limit(limit).with_for_update(skip_locked=True)).all()
            for row in rows:
                session.delete(row)
            return len(rows)


def require_admin(identity: Identity) -> ActorContext:
    if type(identity) is not Identity or identity.role not in {"admin", "super_admin"}:
        raise Forbidden("Admin permission required")
    return identity.actor
