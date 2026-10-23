"""Read-only, allowlisted audit projections; never return arbitrary audit JSON."""
import base64
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
from zoneinfo import ZoneInfo
from sqlalchemy import and_, or_, select
from asi_meal_api.db import models as m
from asi_meal_api.orders import NotFound, OrderError
from asi_meal_api.user_management import actor

ACTIONS = {
    'order_created', 'order_edited', 'received_marked', 'received_reversed', 'menu_created', 'menu_date_assigned',
    'dish_created', 'dish_updated', 'dish_deactivated', 'dish_deleted', 'visitor_created', 'visitor_updated',
    'visitor_deleted', 'employee_import_inserted', 'employee_import_updated', 'employee_import_completed',
    'employee_import_failed', 'first_admin_provisioned', 'auth_login', 'auth_logout', 'password_changed',
    'super_admin_promoted', 'super_admin_recovered', 'user_created', 'user_updated', 'user_role_changed', 'user_disabled',
    'user_reactivated', 'user_password_reset',
}
ENTITIES = {'orders', 'menus', 'menu_dates', 'dishes', 'visitors', 'employee_imports', 'users'}
FIELDS = {
    'order_created': {'is_received'}, 'order_edited': {'is_received'},
    'received_marked': {'is_received'}, 'received_reversed': {'is_received'},
    'menu_date_assigned': {'menu_id'}, 'dish_created': {'category_code', 'is_active'},
    'dish_updated': {'category_code', 'is_active'}, 'dish_deactivated': {'category_code', 'is_active'},
    'dish_deleted': {'category_code', 'is_active'},
    'employee_import_completed': {'status', 'total_rows', 'inserted_rows', 'updated_rows', 'unchanged_rows', 'rejected_rows'},
    'employee_import_failed': {'status', 'total_rows', 'rejected_rows'},
    'user_created': {'role', 'is_enabled'}, 'user_role_changed': {'role'},
    'user_disabled': {'is_enabled'}, 'user_reactivated': {'is_enabled'},
    'user_password_reset': {'password_change_required'}, 'password_changed': {'password_change_required'},
    'super_admin_promoted': {'role'}, 'first_admin_provisioned': {'role'},
    'super_admin_recovered': {'password_change_required'},
}
SAFE_STRINGS = {'role': {'admin', 'assistant_admin', 'super_admin'},
    'category_code': {'vegetable', 'non_vegetable', 'extra_rice'}, 'status': {'processing', 'completed', 'failed'}}
REASONS = {'mistaken_click': 'Mistaken click', 'incorrect_employee_marked': 'Incorrect employee marked',
           'incorrect_order_marked': 'Incorrect order marked', 'incorrect_order_details': 'Incorrect order details', 'other': 'Other reason'}


def values(action, raw):
    if not isinstance(raw, dict): return {}
    result = {}
    for key in FIELDS.get(action, set()):
        value = raw.get(key)
        if key in SAFE_STRINGS and isinstance(value, str) and value in SAFE_STRINGS[key]: result[key] = value
        elif key in {'is_received', 'is_active', 'is_enabled', 'password_change_required'} and type(value) is bool: result[key] = value
        elif key in {'menu_id', 'total_rows', 'inserted_rows', 'updated_rows', 'unchanged_rows', 'rejected_rows'} and type(value) is int and 0 <= value <= 9223372036854775807: result[key] = value
        elif key == 'menu_id' and value is None and key in raw: result[key] = None
    return result


def project(event, user, receipt):
    action = event.action if event.action in ACTIONS else 'unknown'
    entity = event.entity_type if event.entity_type in ENTITIES else None
    reference = None
    if entity and event.entity_key.isascii() and event.entity_key.isdecimal() and len(event.entity_key) <= 19:
        reference = event.entity_key
    elif entity == 'menu_dates':
        try:
            if date.fromisoformat(event.entity_key).isoformat() == event.entity_key:
                reference = event.entity_key
        except ValueError:
            pass
    result = {'id': event.id, 'occurred_at': event.occurred_at, 'actor_id': user.id,
              'actor_display_name': user.display_name, 'action': action, 'entity_type': entity,
              'reference': reference, 'before': values(action, event.before_values), 'after': values(action, event.after_values),
              'reason': REASONS.get(receipt.reason_code) if action == 'received_reversed' and receipt else None}
    # Promotion attribution is self-attested and intentionally distinguished from session identity.
    if action in {'super_admin_promoted', 'super_admin_recovered'} and isinstance(event.after_values, dict) and event.after_values.get('attribution') == 'local_self_attested':
        operator = event.after_values.get('operator')
        if isinstance(operator, str) and 0 < len(operator) <= 255:
            result['local_operator'] = operator
    return result


def fingerprint(filters):
    return hashlib.sha256(json.dumps(filters, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def decode_cursor(cursor, signature):
    try:
        if len(cursor) > 512: raise ValueError
        data = json.loads(base64.urlsafe_b64decode(cursor + '=' * (-len(cursor) % 4)))
        dt = datetime.fromisoformat(data['time'])
        if data['filters'] != signature or dt.tzinfo is None or type(data['id']) is not int or not 1 <= data['id'] <= 9223372036854775807: raise ValueError
        return dt, data['id']
    except (ValueError, TypeError, KeyError, UnicodeError):
        raise OrderError('Invalid activity cursor') from None


class ActivityService:
    def __init__(self, factory): self.factory = factory

    def list(self, context, start, end, actor_id, action, entity, reference, limit, cursor):
        if start and end and start > end: raise OrderError('Invalid date range')
        if action and action not in ACTIONS: raise OrderError('Invalid action')
        if entity and entity not in ENTITIES: raise OrderError('Invalid entity')
        if reference and not entity: raise OrderError('Choose an entity for reference filtering')
        filters = {'start': str(start) if start else None, 'end': str(end) if end else None,
                   'actor': actor_id, 'action': action, 'entity': entity, 'reference': reference, 'limit': limit}
        signature = fingerprint(filters)
        position = decode_cursor(cursor, signature) if cursor else None
        with self.factory() as session, session.begin():
            actor(session, context)
            query = select(m.AuditEvent, m.User, m.ReceiptEvent).join(m.User, m.User.id == m.AuditEvent.actor_user_id).outerjoin(m.ReceiptEvent, m.ReceiptEvent.audit_event_id == m.AuditEvent.id)
            zone = ZoneInfo('Asia/Manila')
            if start: query = query.where(m.AuditEvent.occurred_at >= datetime.combine(start, time.min, zone))
            if end:
                if end == date.max: raise OrderError('Invalid end date')
                query = query.where(m.AuditEvent.occurred_at < datetime.combine(end + timedelta(days=1), time.min, zone))
            if actor_id: query = query.where(m.AuditEvent.actor_user_id == actor_id)
            if action: query = query.where(m.AuditEvent.action == action)
            if entity: query = query.where(m.AuditEvent.entity_type == entity)
            if reference: query = query.where(m.AuditEvent.entity_key == reference)
            if position: query = query.where(or_(m.AuditEvent.occurred_at < position[0], and_(m.AuditEvent.occurred_at == position[0], m.AuditEvent.id < position[1])))
            rows = session.execute(query.order_by(m.AuditEvent.occurred_at.desc(), m.AuditEvent.id.desc()).limit(limit + 1)).all()
            next_cursor = None
            if len(rows) > limit:
                event = rows[limit - 1][0]
                next_cursor = base64.urlsafe_b64encode(json.dumps({'time': event.occurred_at.isoformat(), 'id': event.id, 'filters': signature}).encode()).decode().rstrip('=')
            return {'items': [project(*row) for row in rows[:limit]], 'next_cursor': next_cursor}

    def detail(self, context, event_id):
        with self.factory() as session, session.begin():
            actor(session, context)
            row = session.execute(select(m.AuditEvent, m.User, m.ReceiptEvent).join(m.User, m.User.id == m.AuditEvent.actor_user_id).outerjoin(m.ReceiptEvent, m.ReceiptEvent.audit_event_id == m.AuditEvent.id).where(m.AuditEvent.id == event_id)).one_or_none()
            if row is None: raise NotFound('Activity not found')
            return project(*row)
