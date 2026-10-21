"""Directory/catalog scheduling and operational reads, each owning its transaction.

Existing offerings are retained configurations. Configure a new menu definition
and explicitly assign selected dates instead of silently editing reused menus.
"""

from contextlib import contextmanager
from datetime import date

from sqlalchemy import func, or_, select, text

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
            dish = m.Dish(name=name, category_code=category)
            session.add(dish)
            session.flush()
            result = {"id": dish.id, "name": name, "category_code": category, "is_active": dish.is_active}
            _audit(session, user, "dish_created", "dishes", dish.id, None, result)
            return result

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

    def create_menu(self, actor, label, dish_ids, assignments):
        label = None if label is None else _text(label)
        if (not isinstance(dish_ids, (list, tuple)) or not 1 <= len(dish_ids) <= 100
                or any(type(i) is not int or not 0 < i <= 9223372036854775807 for i in dish_ids)
                or len(set(dish_ids)) != len(dish_ids)):
            raise OrderError("Expected distinct dish identifiers")
        assignments = self._dates(assignments) if assignments else []
        with self._transaction(actor) as (session, user):
            rows = self._lock_dates(session, assignments)
            dishes = session.scalars(select(m.Dish).where(m.Dish.id.in_(dish_ids)).order_by(m.Dish.id)
                                     .with_for_update(read=True)).all()
            if len(dishes) != len(dish_ids):
                raise NotFound("Dish not found")
            if any(not d.is_active for d in dishes):
                raise Conflict("Inactive dishes cannot be selected for a new menu")
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
               received=None, limit=20, offset=0):
        _page("", limit, offset)
        if start is not None and end is not None and end < start:
            raise OrderError("Invalid date range")
        with self._transaction(actor) as (session, _):
            total = select(func.sum(m.OrderItem.line_total)).where(m.OrderItem.order_id == m.Order.id).scalar_subquery()
            statement = select(m.Order.id.label("order_id"), m.Order.service_date, m.Order.menu_id,
                m.Order.employee_number, m.Order.visitor_id, m.Order.customer_name_snapshot.label("customer_name"),
                m.Order.is_received, m.Order.version, total.label("total"))
            for value, predicate in ((start, m.Order.service_date >= start if start else None),
                (end, m.Order.service_date <= end if end else None),
                (employee_number, m.Order.employee_number == employee_number), (visitor_id, m.Order.visitor_id == visitor_id),
                (received, m.Order.is_received == received)):
                if value is not None:
                    statement = statement.where(predicate)
            return [dict(row) for row in session.execute(statement.order_by(m.Order.service_date.desc(), m.Order.id.desc())
                                                        .limit(limit).offset(offset)).mappings()]

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
