"""Authentication-only HTTP adapter and verified actor dependencies."""

from dataclasses import dataclass
import ipaddress
import json
import os
import threading
import time
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, SecretStr

from asi_meal_api.auth import AuthService, SessionResult, require_admin


@dataclass(frozen=True, slots=True)
class AuthSettings:
    origins: frozenset[str]
    mode: str = "https"

    def __post_init__(self):
        if self.mode not in {"https", "development"} or not self.origins:
            raise ValueError("Explicit authentication origins and cookie profile are required")
        for origin in self.origins:
            parsed = urlsplit(origin)
            try:
                port = parsed.port
            except ValueError:
                raise ValueError("Invalid trusted origin") from None
            if (not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment
                    or parsed.scheme != ("https" if self.mode == "https" else "http") or port == 0):
                raise ValueError("Invalid trusted origin")
            if self.mode == "development" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
                raise ValueError("Development origins must be loopback only")

    @property
    def cookie(self):
        return "__Host-asi_session" if self.mode == "https" else "asi_dev_session"

    def check_transport(self, request):
        if self.mode == "https":
            if request.url.scheme != "https":
                raise HTTPException(403, "HTTPS required")
        else:
            try:
                local = ipaddress.ip_address(request.client.host).is_loopback
            except (ValueError, AttributeError):
                local = False
            if not local or request.url.hostname not in {"localhost", "127.0.0.1", "::1"}:
                raise HTTPException(403, "Loopback development access required")

    def check_origin(self, request):
        if request.headers.get("origin") not in self.origins:
            raise HTTPException(403, "Request rejected")


class LoginLimiter:
    """Bounded per-process abuse guard, not a session store or shared deployment limit."""
    def __init__(self):
        self._entries = {}
        self._lock = threading.Lock()

    def check(self, client: str):
        now = time.monotonic()
        with self._lock:
            self._entries = {key: value for key, value in self._entries.items() if now - value[0] < 60}
            if client not in self._entries and len(self._entries) >= 1024:
                raise HTTPException(429, "Try again later")
            start, count = self._entries.get(client, (now, 0))
            if count >= 5:
                raise HTTPException(429, "Try again later")
            self._entries[client] = (start, count + 1)


@dataclass
class AuthRuntime:
    service: AuthService
    settings: AuthSettings
    limiter: LoginLimiter


def runtime_from_environment():
    settings = AuthSettings(frozenset(filter(None, os.environ.get("ASI_AUTH_ORIGINS", "").split(","))),
                            os.environ.get("ASI_AUTH_MODE", "https"))
    url = os.environ.get("ASI_DATABASE_URL", "")
    if not url.startswith("postgresql+psycopg://"):
        raise ValueError("Explicit PostgreSQL authentication configuration required")
    engine = create_engine(url, hide_parameters=True)
    return AuthRuntime(AuthService(sessionmaker(bind=engine)), settings, LoginLimiter()), engine


def runtime(request: Request) -> AuthRuntime:
    value = getattr(request.app.state, "auth", None)
    if value is None:
        raise HTTPException(503, "Authentication unavailable")
    value.settings.check_transport(request)
    return value


def verified_identity(request: Request):
    value = runtime(request)
    unsafe = request.method not in {"GET", "HEAD", "OPTIONS"}
    if unsafe:
        value.settings.check_origin(request)
    user = value.service.current(request.cookies.get(value.settings.cookie), request.headers.get("x-csrf-token"),
                                 verify_csrf=unsafe).user
    if user.password_change_required:
        raise HTTPException(403, "Password change required")
    return user


def authenticated_actor(request: Request):
    return verified_identity(request).actor


def admin_actor(request: Request):
    return require_admin(verified_identity(request))


def user_response(result: SessionResult):
    return {"user": {"id": result.user.id, "login_name": result.user.login_name,
                     "display_name": result.user.display_name, "role": result.user.role,
                     "password_change_required": result.user.password_change_required},
            "csrf_token": result.csrf_token}


router = APIRouter(prefix="/auth", tags=["Authentication"])


class PasswordChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: SecretStr
    new_password: SecretStr


@router.post("/change-password")
def change_password(body: PasswordChange, request: Request):
    value = runtime(request)
    value.settings.check_origin(request)
    value.limiter.check(request.client.host if request.client else "unknown")
    try:
        result = value.service.change_password(request.cookies.get(value.settings.cookie),
            request.headers.get("x-csrf-token"), body.current_password.get_secret_value(), body.new_password.get_secret_value())
    except ValueError as exc:
        from asi_meal_api.auth import ProvisioningRejected
        if isinstance(exc, ProvisioningRejected):
            raise HTTPException(422, str(exc)) from None
        raise
    return user_response(result)


@router.post("/login")
async def login(request: Request):
    value = runtime(request)
    value.settings.check_origin(request)
    if request.headers.get("x-asi-request") != "1" or request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        raise HTTPException(403, "Request rejected")
    value.limiter.check(request.client.host if request.client else "unknown")
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > 8192:
            raise HTTPException(413, "Request too large")
        data.extend(chunk)
    try:
        payload = json.loads(data.decode("utf-8"))
        if type(payload) is not dict or set(payload) != {"login_name", "password"}:
            raise ValueError
    except (ValueError, UnicodeError):
        raise HTTPException(400, "Invalid login request") from None
    result = await run_in_threadpool(value.service.login, payload["login_name"], payload["password"],
                                     request.cookies.get(value.settings.cookie))
    response = JSONResponse(user_response(result))
    response.set_cookie(value.settings.cookie, result.token, max_age=int(value.service.lifetime.total_seconds()),
                        expires=result.expires_at, secure=value.settings.mode == "https", httponly=True,
                        samesite="lax", path="/")
    return response


@router.get("/me")
def me(request: Request):
    value = runtime(request)
    origin = request.headers.get("origin")
    if request.headers.get("sec-fetch-site") == "cross-site" or (origin is not None and origin not in value.settings.origins):
        raise HTTPException(403, "Request rejected")
    return user_response(value.service.current(request.cookies.get(value.settings.cookie)))


@router.post("/logout", status_code=204)
def logout(request: Request):
    value = runtime(request)
    value.settings.check_origin(request)
    value.service.logout(request.cookies.get(value.settings.cookie), request.headers.get("x-csrf-token"))
    response = Response(status_code=204)
    response.delete_cookie(value.settings.cookie, path="/", secure=value.settings.mode == "https", httponly=True, samesite="lax")
    return response
