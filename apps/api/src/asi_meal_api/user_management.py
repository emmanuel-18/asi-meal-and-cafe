"""Transactional account administration. Secrets never enter audit payloads."""
from datetime import datetime, timezone
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
from asi_meal_api.db import models as m
from asi_meal_api.orders import ActorContext, Conflict, Forbidden, NotFound, OrderError
from asi_meal_api.auth import Passwords


def safe(user):
    return {"id": user.id, "login_name": user.login_name, "display_name": user.display_name,
            "role": user.role_code, "is_enabled": user.is_enabled,
            "password_change_required": user.password_change_required,
            "created_at": user.created_at, "updated_at": user.updated_at}


def actor(session, context):
    if type(context) is not ActorContext:
        raise Forbidden("Permission denied")
    user = session.scalar(select(m.User).where(m.User.id == context.user_id).with_for_update())
    if user is None or not user.is_enabled or user.role_code != "super_admin" or user.password_change_required:
        raise Forbidden("Permission denied")
    return user


def event(session, actor_id, target_id, action, before, after, reason=None):
    session.add(m.AuditEvent(actor_user_id=actor_id, action=action, entity_type="users", entity_key=str(target_id),
                             before_values=before, after_values=after, reason=reason))


def revoke(session, user_id, now):
    session.execute(update(m.AuthSession).where(m.AuthSession.user_id == user_id,
        m.AuthSession.revoked_at.is_(None)).values(revoked_at=now))


def name(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 255 or '\x00' in value:
        raise OrderError("A nonblank name of at most 255 characters is required")
    return value.strip()


class UserService:
    def __init__(self, sessions, passwords=None):
        self.sessions = sessions
        self.passwords = passwords or Passwords()

    def list(self, context, q, limit, offset):
        with self.sessions() as session, session.begin():
            actor(session, context)
            query = select(m.User).where((m.User.login_name.icontains(q, autoescape=True)) |
                                         (m.User.display_name.icontains(q, autoescape=True)))
            return [safe(u) for u in session.scalars(query.order_by(m.User.id).offset(offset).limit(limit))]

    def create(self, context, login, display, role, password):
        login, display = name(login), name(display)
        if role not in {"admin", "assistant_admin"}:
            raise OrderError("Invalid role")
        try:
            encoded = self.passwords.hash(password)
        except ValueError as exc:
            raise OrderError(str(exc)) from None
        try:
            with self.sessions() as session, session.begin():
                a = actor(session, context)
                user = m.User(login_name=login, display_name=display, role_code=role, password_hash=encoded,
                              is_enabled=True, password_change_required=True)
                session.add(user)
                session.flush()
                event(session, a.id, user.id, "user_created", None,
                      {"login_name": login, "display_name": display, "role": role, "is_enabled": True})
                return safe(user)
        except IntegrityError:
            raise Conflict("Account could not be created; check the login name") from None

    def change(self, context, target_id, expected_updated_at, display, role, enabled, password=None):
        if display is not None:
            display = name(display)
        if role is not None and role not in {"admin", "assistant_admin"}:
            raise OrderError("Invalid role")
        try:
            encoded = self.passwords.hash(password) if password is not None else None
        except ValueError as exc:
            raise OrderError(str(exc)) from None
        with self.sessions() as session, session.begin():
            # Serialize account changes, including future last-Super-Admin operations.
            session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": int.from_bytes(b"ASISUPER", "big")})
            a = actor(session, context)
            target = session.scalar(select(m.User).where(m.User.id == target_id).with_for_update())
            if target is None:
                raise NotFound("Account not found")
            if target.updated_at != expected_updated_at:
                raise Conflict("Account changed; refresh and review")
            # Super Admin changes, including self-disable/demotion, are CLI-only.
            if target.role_code == "super_admin":
                raise Forbidden("Super Admin accounts cannot be changed here")
            before = {"display_name": target.display_name, "role": target.role_code, "is_enabled": target.is_enabled}
            now = datetime.now(timezone.utc)
            if display is not None: target.display_name = display
            if role is not None: target.role_code = role
            if enabled is not None: target.is_enabled = enabled
            after = {"display_name": target.display_name, "role": target.role_code, "is_enabled": target.is_enabled}
            if before != after:
                if before['role'] != after['role'] or before['is_enabled'] != after['is_enabled']:
                    revoke(session, target.id, now)
                if before['display_name'] != after['display_name']:
                    event(session, a.id, target.id, "user_updated", {"display_name": before['display_name']}, {"display_name": after['display_name']})
                if before['role'] != after['role']:
                    event(session, a.id, target.id, "user_role_changed", {"role": before['role']}, {"role": after['role']})
                if before['is_enabled'] != after['is_enabled']:
                    event(session, a.id, target.id, "user_reactivated" if after['is_enabled'] else "user_disabled",
                          {"is_enabled": before['is_enabled']}, {"is_enabled": after['is_enabled']})
            if encoded is not None:
                target.password_hash = encoded
                target.password_change_required = True
                revoke(session, target.id, now)
                event(session, a.id, target.id, "user_password_reset", None, {"password_change_required": True})
            if before != after or encoded is not None:
                target.updated_at = now
            return safe(target)
