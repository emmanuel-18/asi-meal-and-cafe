"""HTTP adapters for Super Admin account management."""
from datetime import datetime
from typing import Annotated, Literal
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from asi_meal_api.auth_http import authenticated_actor, runtime
from asi_meal_api.orders import ActorContext
from asi_meal_api.user_management import UserService

router = APIRouter(prefix="/api/users", tags=["Users"])
Actor = Annotated[ActorContext, Depends(authenticated_actor)]
Role = Literal["admin", "assistant_admin"]


class CreateUser(BaseModel):
    model_config = ConfigDict(extra="forbid")
    login_name: str = Field(min_length=1, max_length=255)
    display_name: str = Field(min_length=1, max_length=255)
    role: Role
    temporary_password: SecretStr


class ChangeUser(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_updated_at: datetime
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    role: Role | None = None
    is_enabled: bool | None = None
    temporary_password: SecretStr | None = None


def service(request):
    value = runtime(request).service
    return UserService(value.session_factory, value.passwords)


@router.get("")
def list_users(request: Request, actor: Actor, q: Annotated[str, Query(max_length=100)] = "",
               limit: Annotated[int, Query(ge=1, le=100)] = 20,
               offset: Annotated[int, Query(ge=0, le=10000)] = 0):
    return service(request).list(actor, q, limit, offset)


@router.post("", status_code=201)
def create_user(body: CreateUser, request: Request, actor: Actor):
    return service(request).create(actor, body.login_name, body.display_name, body.role, body.temporary_password.get_secret_value())


@router.patch("/{user_id}")
def change_user(user_id: int, body: ChangeUser, request: Request, actor: Actor):
    return service(request).change(actor, user_id, body.expected_updated_at, body.display_name, body.role,
        body.is_enabled, body.temporary_password.get_secret_value() if body.temporary_password is not None else None)
