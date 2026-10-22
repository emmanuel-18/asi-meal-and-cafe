"""Directory/catalog scheduling and operational reads, each owning its transaction.

Existing offerings are retained configurations. Configure a new menu definition
and explicitly assign selected dates instead of silently editing reused menus.
"""

from contextlib import contextmanager
from datetime import date
import hashlib
import json
import re

from sqlalchemy import String, case, cast, func, literal, or_, select, text
from sqlalchemy.dialects.postgresql import aggregate_order_by

from asi_meal_api.db import models as m
from asi_meal_api.orders import Conflict, NotFound, OrderError, OrderService, authorize_actor


def _text(value, maximum=200):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or "\x00" in value:
        raise OrderError("Expected nonblank bounded text")
    return value.strip()


def _page(q, limit, offset):
    if not isinstance(q, str) or len(q) > 100 or "\x00" in q:
        raise OrderError("Invalid search")
    if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or not 0 <= offset <= 10000:
        raise OrderError("Invalid pagination")
    return q.strip()


def _search(column, q):
    # Literal substring search: submitted % and _ are not SQL wildcards.
    return column.icontains(q, autoescape=True)


def _audit(session, actor, action, entity, key, before, after):
    session.add(m.AuditEvent(actor_user_id=actor.id, action=action, entity_type=entity,
                            entity_key=str(key), before_values=before, after_values=after))


class BusinessService:
    def __init__(self, session_factory):
        self._sessions = session_factory

    @contextmanager
    def _transaction(self, actor, *, admin=False):
        with self._sessions() as session, session.begin():
            user = authorize_actor(session, actor, admin=admin)
            yield session, user

    def employees(self, actor, q="", limit=20, offset=0):
        q = _page(q, limit, offset)
        with self._transaction(actor) as (session, _):
            statement = select(m.Employee.employee_number, m.Employee.full_name, m.Employee.position,
                               m.Employee.campaign, m.Employee.line_of_business)
            if q:
                statement = statement.where(or_(_search(m.Employee.employee_number, q), _search(m.Employee.full_name, q)))
            return [dict(row) for row in session.execute(statement.order_by(m.Employee.employee_number)
                                                        .limit(limit).offset(offset)).mappings()]

    def visitors(self, actor, q="", limit=20, offset=0):
        q = _page(q, limit, offset)
        with self._transaction(actor) as (session, _):
            statement = select(m.Visitor.id, m.Visitor.display_name)
            if q:
                statement = statement.where(_search(m.Visitor.display_name, q))
            return [dict(row) for row in session.execute(statement.order_by(m.Visitor.id)
                                                        .limit(limit).offset(offset)).mappings()]

    def create_visitor(self, actor, display_name):
        name = _text(display_name)
        with self._transaction(actor) as (session, user):
            visitor = m.Visitor(display_name=name, created_by=user.id)
            session.add(visitor)
            session.flush()
            result = {"id": visitor.id, "display_name": visitor.display_name}
            _audit(session, user, "visitor_created", "visitors", visitor.id, None, result)
            return result

    def change_visitor(self, actor, visitor_id, expected_name, name=None):
        expected_name = _text(expected_name)
        name = _text(name) if name is not None else None
        with self._transaction(actor) as (session, user):
            visitor = session.scalar(select(m.Visitor).where(m.Visitor.id == visitor_id).with_for_update())
            if visitor is None:
                raise NotFound("Visitor not found")
            if visitor.display_name != expected_name:
                raise Conflict("Visitor changed; refresh before trying again")
            before = {"id": visitor.id, "display_name": visitor.display_name}
            if name is None:
                if session.scalar(select(m.Order.id).where(m.Order.visitor_id == visitor_id).limit(1)):
                    raise Conflict("Visitor is used by an order and cannot be deleted")
                _audit(session, user, "visitor_deleted", "visitors", visitor.id, before, None)
                session.delete(visitor)
                return
            visitor.display_name = name
            after = {"id": visitor.id, "display_name": name}
            if before != after:
                _audit(session, user, "visitor_updated", "visitors", visitor.id, before, after)
            return after

    def dishes(self, actor, q="", limit=20, offset=0, category=None, active=None):
        q = _page(q, limit, offset)
        if category is not None and category not in {"vegetable", "non_vegetable", "extra_rice"}:
            raise OrderError("Unknown item category")
        if active is not None and type(active) is not bool:
            raise OrderError("Invalid active filter")
        with self._transaction(actor) as (session, _):
            statement = select(m.Dish.id, m.Dish.name, m.Dish.category_code, m.Dish.is_active)
            if q:
                statement = statement.where(_search(m.Dish.name, q))
            if category is not None:
                statement = statement.where(m.Dish.category_code == category)
            if active is not None:
                statement = statement.where(m.Dish.is_active == active)
            return [dict(row) for row in session.execute(statement.order_by(m.Dish.id)
                                                        .limit(limit).offset(offset)).mappings()]

    def create_dish(self, actor, name, category):
        name = _text(name)
        with self._transaction(actor) as (session, user):
            if category not in {"vegetable", "non_vegetable", "extra_rice"} or session.get(m.ItemCategory, category) is None:
                raise OrderError("Unknown item category")
            if category == "extra_rice" and name.lower() == "extra rice":
                self._lock_default_rice(session)
                if self._find_default_rice(session):
                    raise Conflict("The default Extra Rice dish already exists")
            dish = m.Dish(name=name, category_code=category)
            session.add(dish)
            session.flush()
            result = {"id": dish.id, "name": name, "category_code": category, "is_active": dish.is_active}
            _audit(session, user, "dish_created", "dishes", dish.id, None, result)
            return result

    def change_dish(self, actor, dish_id, expected_name, expected_category, name=None, category=None):
        expected_name = _text(expected_name)
        name = _text(name) if name is not None else None
        if expected_category not in {"vegetable", "non_vegetable"} or (name is not None and category not in {"vegetable", "non_vegetable"}):
            raise OrderError("Only meal dishes can be edited or deleted")
        with self._transaction(actor) as (session, user):
            dish = session.scalar(select(m.Dish).where(m.Dish.id == dish_id).with_for_update())
            if dish is None:
                raise NotFound("Dish not found")
            if dish.name != expected_name or dish.category_code != expected_category:
                raise Conflict("Dish changed; refresh before trying again")
            before = {"id": dish.id, "name": dish.name, "category_code": dish.category_code, "is_active": dish.is_active}
            if name is None:
                if session.scalar(select(m.MenuItem.id).where(m.MenuItem.dish_id == dish_id).limit(1)):
                    if dish.is_active:
                        dish.is_active = False
                        _audit(session, user, "dish_deactivated", "dishes", dish.id, before, {**before, "is_active": False})
                    return
                _audit(session, user, "dish_deleted", "dishes", dish.id, before, None)
                session.delete(dish)
                return
            dish.name, dish.category_code = name, category
            after = {"id": dish.id, "name": name, "category_code": category, "is_active": dish.is_active}
            if before != after:
                _audit(session, user, "dish_updated", "dishes", dish.id, before, after)
            return after

    @staticmethod
    def _lock_default_rice(session):
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": int.from_bytes(b"ASIRICE1", "big")})

    @staticmethod
    def _find_default_rice(session):
        # Exact normalized name only; retain legacy duplicates and prefer the oldest active match.
        return session.scalar(select(m.Dish).where(m.Dish.category_code == "extra_rice", m.Dish.is_active.is_(True),
                              func.lower(func.trim(m.Dish.name)) == "extra rice").order_by(m.Dish.id).limit(1))

    def menu_defaults(self, actor):
        with self._transaction(actor) as (session, _):
            category = session.get(m.ItemCategory, "extra_rice")
            if category is None:
                raise Conflict("Extra Rice category is not configured")
            return {"extra_rice_price": category.default_unit_price}

    @staticmethod
    def _dates(assignments):
        if not isinstance(assignments, (list, tuple)) or not 1 <= len(assignments) <= 366:
            raise OrderError("Expected between one and 366 explicit date assignments")
        days = [a[0] for a in assignments]
        if any(type(day) is not date for day in days) or len(set(days)) != len(days):
            raise OrderError("Invalid or duplicate service dates")
        if any(old is not None and (type(old) is not int or not 0 < old <= 9223372036854775807)
               for _, old in assignments):
            raise OrderError("Invalid expected menu identifier")
        return sorted(assignments)

    @staticmethod
    def _lock_dates(session, assignments):
        # Also serializes creation of absent date rows. Existing order writers use
        # the same date -> menu lock ordering, without needing this advisory lock.
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": int.from_bytes(b"ASIMENU1", "big")})
        rows = {}
        for day, expected in assignments:
            row = session.scalar(select(m.MenuDate).where(m.MenuDate.service_date == day).with_for_update())
            if (row.menu_id if row else None) != expected:
                raise Conflict("Date assignment changed; reload before assigning")
            rows[day] = row
        return rows

    @staticmethod
    def _assign(session, user, menu_id, assignments, rows):
        for day, expected in assignments:
            if expected == menu_id:
                continue
            if rows[day] is None:
                session.add(m.MenuDate(service_date=day, menu_id=menu_id))
            else:
                rows[day].menu_id = menu_id
            _audit(session, user, "menu_date_assigned", "menu_dates", day.isoformat(),
                   {"menu_id": expected}, {"menu_id": menu_id})

    @staticmethod
    def _menu(session, menu_id):
        menu = session.get(m.Menu, menu_id)
        if menu is None:
            raise NotFound("Menu not found")
        items = session.scalars(select(m.MenuItem).where(m.MenuItem.menu_id == menu_id).order_by(m.MenuItem.id)).all()
        return {"id": menu.id, "label": menu.label, "items": [
            {"id": i.id, "dish_id": i.dish_id, "item_name": i.item_name, "category_code": i.category_code,
             "unit_price": i.unit_price} for i in items]}

    def create_menu(self, actor, label, dish_ids, assignments, include_default_rice=False, dish_changes=None):
        label = None if label is None else _text(label)
        if (not isinstance(dish_ids, (list, tuple)) or len(dish_ids) > 100
                or (not dish_ids and not include_default_rice)
                or any(type(i) is not int or not 0 < i <= 9223372036854775807 for i in dish_ids)
                or len(set(dish_ids)) != len(dish_ids)):
            raise OrderError("Expected distinct dish identifiers")
        assignments = self._dates(assignments) if assignments else []
        if include_default_rice and len(dish_ids) > 99:
            raise OrderError("Select at most 99 dishes when Extra Rice is included")
        dish_changes = dish_changes or []
        if dish_changes and (len(assignments) != 1 or len(dish_changes) > 100 or len({c["id"] for c in dish_changes}) != len(dish_changes)):
            raise OrderError("Dish changes require one date and distinct dish identifiers")
        with self._transaction(actor) as (session, user):
            rows = self._lock_dates(session, assignments)
            for change in sorted(dish_changes, key=lambda c: c["id"]):
                dish = session.scalar(select(m.Dish).where(m.Dish.id == change["id"]).with_for_update())
                if dish is None:
                    raise NotFound("Dish not found")
                if not dish.is_active or dish.name != change["expected_name"] or dish.category_code != change["expected_category"]:
                    raise Conflict("Dish changed; refresh before saving")
                before = {"id": dish.id, "name": dish.name, "category_code": dish.category_code, "is_active": dish.is_active}
                if change["delete"]:
                    if change["name"] is not None or change["category_code"] is not None or dish.id in dish_ids:
                        raise OrderError("Deleted dishes cannot be selected or edited")
                    dish.is_active = False
                    _audit(session, user, "dish_deactivated", "dishes", dish.id, before, {**before, "is_active": False})
                else:
                    if change["name"] is None or change["category_code"] not in {"vegetable", "non_vegetable"}:
                        raise OrderError("A dish edit requires a name and category")
                    dish.name = _text(change["name"])
                    dish.category_code = change["category_code"]
                    after = {"id": dish.id, "name": dish.name, "category_code": dish.category_code, "is_active": True}
                    if before != after:
                        _audit(session, user, "dish_updated", "dishes", dish.id, before, after)
            session.flush()
            dishes = session.scalars(select(m.Dish).where(m.Dish.id.in_(dish_ids)).order_by(m.Dish.id)
                                     .with_for_update(read=True)).all()
            if len(dishes) != len(dish_ids):
                raise NotFound("Dish not found")
            if any(not d.is_active for d in dishes):
                raise Conflict("Inactive dishes cannot be selected for a new menu")
            if include_default_rice:
                if any(d.category_code == "extra_rice" for d in dishes):
                    raise OrderError("Extra Rice is included automatically")
                self._lock_default_rice(session)
                rice = self._find_default_rice(session)
                if rice is None:
                    rice = m.Dish(name="Extra Rice", category_code="extra_rice")
                    session.add(rice)
                    session.flush()
                    _audit(session, user, "dish_created", "dishes", rice.id, None,
                           {"id": rice.id, "name": rice.name, "category_code": rice.category_code, "is_active": rice.is_active})
                dishes.append(rice)
            prices = {c.code: c.default_unit_price for c in session.scalars(select(m.ItemCategory)
                       .order_by(m.ItemCategory.code).with_for_update(read=True))}
            menu = m.Menu(label=label, created_by=user.id)
            session.add(menu)
            session.flush()
            for dish in dishes:
                session.add(m.MenuItem(menu_id=menu.id, dish_id=dish.id, item_name=dish.name,
                                       category_code=dish.category_code, unit_price=prices[dish.category_code]))
            session.flush()
            result = self._menu(session, menu.id)
            audited = {**result, "items": [{**i, "unit_price": format(i["unit_price"], ".2f")} for i in result["items"]]}
            _audit(session, user, "menu_created", "menus", menu.id, None, audited)
            self._assign(session, user, menu.id, assignments, rows)
            return result

    def assign_menu(self, actor, menu_id, assignments):
        assignments = self._dates(assignments)
        with self._transaction(actor) as (session, user):
            rows = self._lock_dates(session, assignments)
            if session.scalar(select(m.Menu).where(m.Menu.id == menu_id).with_for_update()) is None:
                raise NotFound("Menu not found")
            self._assign(session, user, menu_id, assignments, rows)
            return {"menu_id": menu_id, "service_dates": [day for day, _ in assignments]}

    def menu_by_id(self, actor, menu_id):
        """Read retained offerings for an order's recorded menu, independent of scheduling."""
        with self._transaction(actor) as (session, _):
            return self._menu(session, menu_id)

    def menu_for_date(self, actor, service_date):
        if type(service_date) is not date:
            raise OrderError("Expected a service date")
        with self._transaction(actor) as (session, _):
            assignment = session.scalar(select(m.MenuDate).where(m.MenuDate.service_date == service_date)
                                        .with_for_update(read=True))
            if assignment is None:
                raise NotFound("No menu assigned to service date")
            return {"service_date": service_date, **self._menu(session, assignment.menu_id)}

    def import_errors(self, actor, import_id):
        with self._transaction(actor, admin=True) as (session, _):
            rows = session.execute(select(m.EmployeeImportRow.row_number, m.EmployeeImportRow.issues)
                .where(m.EmployeeImportRow.import_id == import_id, m.EmployeeImportRow.outcome == "rejected")
                .order_by(m.EmployeeImportRow.row_number).limit(101)).all()
            # Only record numbers and already allowlisted field/error codes.
            return {"errors": [{"row_number": r.row_number, "issues": r.issues} for r in rows[:100]],
                    "errors_truncated": len(rows) > 100}

    def orders(self, actor, *, start=None, end=None, employee_number=None, visitor_id=None,
               received=None, limit=20, offset=0, pending_first=False):
        _page("", limit, offset)
        if start is not None and end is not None and end < start:
            raise OrderError("Invalid date range")
        with self._transaction(actor) as (session, _):
            statement = self._order_rows(start, end, employee_number, visitor_id, received, pending_first)
            return [dict(row) for row in session.execute(statement.limit(limit).offset(offset)).mappings()]

    @staticmethod
    def _order_filter(statement, start, end, employee_number, visitor_id, received):
        for value, predicate in ((start, m.Order.service_date >= start if start else None),
            (end, m.Order.service_date <= end if end else None),
            (employee_number, m.Order.employee_number == employee_number), (visitor_id, m.Order.visitor_id == visitor_id),
            (received, m.Order.is_received == received)):
            if value is not None:
                statement = statement.where(predicate)
        return statement

    @classmethod
    def _order_rows(cls, start, end, employee_number, visitor_id, received, pending_first):
        total = select(func.sum(m.OrderItem.line_total)).where(m.OrderItem.order_id == m.Order.id).scalar_subquery()
        statement = select(m.Order.id.label("order_id"), m.Order.service_date, m.Order.menu_id,
            m.Order.employee_number, m.Order.visitor_id, m.Order.customer_name_snapshot.label("customer_name"),
            m.Order.is_received, m.Order.version, total.label("total"))
        statement = cls._order_filter(statement, start, end, employee_number, visitor_id, received)
        ordering = (m.Order.is_received.asc(), m.Order.service_date.desc(), m.Order.id.desc()) if pending_first else (m.Order.service_date.desc(), m.Order.id.desc())
        return statement.order_by(*ordering)

    def orders_page(self, actor, *, start=None, end=None, employee_number=None, visitor_id=None,
                    received=None, limit=20, offset=0, revision=None):
        _page("", limit, offset)
        if start is not None and end is not None and end < start:
            raise OrderError("Invalid date range")
        if (offset and revision is None) or (revision is not None and not re.fullmatch(r"[0-9a-f]{64}", revision)):
            raise OrderError("A valid listing revision is required for later pages")
        with self._sessions() as session, session.begin():
            session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            authorize_actor(session, actor)
            key = cast(m.Order.id, String) + literal(':') + cast(m.Order.version, String) + literal(':') + cast(m.Order.is_received, String) + literal(':') + cast(m.Order.service_date, String)
            serialized = func.coalesce(func.string_agg(key, aggregate_order_by(literal(','), m.Order.id)), '')
            fingerprint = select(func.encode(func.sha256(func.convert_to(serialized, 'UTF8')), 'hex'))
            fingerprint = self._order_filter(fingerprint, start, end, employee_number, visitor_id, received)
            digest = session.scalar(fingerprint)
            filters = [str(start) if start else None, str(end) if end else None, employee_number, visitor_id, received, limit]
            current = hashlib.sha256(json.dumps([filters, digest], separators=(',', ':')).encode()).hexdigest()
            if revision is not None and revision != current:
                raise Conflict("Order listing changed; restart from the first page")
            rows = session.execute(self._order_rows(start, end, employee_number, visitor_id, received, True).limit(limit).offset(offset)).mappings()
            return {"revision": current, "orders": [dict(row) for row in rows]}

    def order_overview(self, actor, day):
        if type(day) is not date:
            raise OrderError("Expected a service date")
        with self._transaction(actor) as (session, _):
            total = select(func.sum(m.OrderItem.line_total)).where(m.OrderItem.order_id == m.Order.id).scalar_subquery()
            row = session.execute(select(
                func.count().filter(m.Order.is_received.is_(False)).label("pending"),
                func.count().filter(m.Order.is_received.is_(True)).label("received"),
                func.count().label("total"),
                func.coalesce(func.sum(case((m.Order.is_received.is_(True), total), else_=0)), 0).label("recognized_sales"),
            ).where(m.Order.service_date == day)).mappings().one()
            return dict(row)

    def order_detail(self, actor, order_id):
        with self._transaction(actor) as (session, _):
            order = session.scalar(select(m.Order).where(m.Order.id == order_id).with_for_update(read=True))
            if order is None:
                raise NotFound("Order not found")
            snapshot = OrderService._snapshot(session, order)
            return {"order_id": order.id, "service_date": order.service_date, "menu_id": order.menu_id,
                    "employee_number": order.employee_number, "visitor_id": order.visitor_id,
                    "customer_name": order.customer_name_snapshot, "position": order.position_snapshot,
                    "campaign": order.campaign_snapshot, "line_of_business": order.line_of_business_snapshot, **snapshot}
