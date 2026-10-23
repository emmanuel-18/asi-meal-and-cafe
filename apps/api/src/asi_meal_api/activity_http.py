"""Super Admin-only read-only activity API."""
from datetime import date
from typing import Annotated
from fastapi import APIRouter, Depends, Path, Query, Request
from asi_meal_api.activity import ActivityService
from asi_meal_api.auth_http import authenticated_actor, runtime
from asi_meal_api.orders import ActorContext

router = APIRouter(prefix='/api/activity', tags=['Activity'])
Actor = Annotated[ActorContext, Depends(authenticated_actor)]


@router.get('')
def listing(request: Request, actor: Actor, start: date | None = None, end: date | None = None,
            actor_id: Annotated[int | None, Query(gt=0, le=9223372036854775807)] = None,
            action: Annotated[str | None, Query(max_length=80, pattern=r'^[a-z_]+$')] = None,
            entity: Annotated[str | None, Query(max_length=40, pattern=r'^[a-z_]+$')] = None,
            reference: Annotated[str | None, Query(max_length=40, pattern=r'^[0-9-]+$')] = None,
            limit: Annotated[int, Query(ge=1, le=100)] = 20,
            cursor: Annotated[str | None, Query(max_length=512)] = None):
    return ActivityService(runtime(request).service.session_factory).list(actor, start, end, actor_id, action, entity, reference, limit, cursor)


@router.get('/{event_id}')
def detail(request: Request, actor: Actor, event_id: Annotated[int, Path(gt=0, le=9223372036854775807)]):
    return ActivityService(runtime(request).service.session_factory).detail(actor, event_id)
