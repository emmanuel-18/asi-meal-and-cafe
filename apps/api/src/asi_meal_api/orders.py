"""Transactional order use cases, independent of the HTTP/session adapter.

ActorContext is a trusted integration boundary, never an HTTP body DTO. The
verified session provider constructs it; stored enabled/role data is rechecked
under a shared lock for every call. Each call owns one Session transaction.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from types import MappingProxyType
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from asi_meal_api.db import models as m
from asi_meal_api.db.base import Money


CORRECTION_REASONS = MappingProxyType({
    "mistaken_click": "Mistaken click",
    "incorrect_employee_marked": "Incorrect employee marked",
    "incorrect_order_marked": "Incorrect order marked",
    "incorrect_order_details": "Incorrect order details",
    "other": "Other reason",
})
PAYMENT_CODES = frozenset({"cash", "gcash", "sd", "incentive", "finance"})


class OrderError(ValueError):
    """Safe domain rejection; messages deliberately exclude submitted data."""


class Forbidden(OrderError):
    pass


class NotFound(OrderError):
    pass


class Conflict(OrderError):
    pass


@dataclass(frozen=True, slots=True)
class ActorContext:
    user_id: int


@dataclass(frozen=True, slots=True)
class ItemSelection:
    menu_item_id: int
    quantity: int


@dataclass(frozen=True, slots=True)
class Allocation:
    category: str
    amount: Decimal


@dataclass(frozen=True, slots=True)
class CreateOrder:
    request_key: UUID
    service_date: date
    menu_id: int
    items: tuple[ItemSelection, ...]
    allocations: tuple[Allocation, ...] = ()
    employee_number: str | None = None
    visitor_id: int | None = None


@dataclass(frozen=True, slots=True)
class QuantityChange:
    line_id: int
    quantity: int


@dataclass(frozen=True, slots=True)
class EditPending:
    # No customer/date/menu/price/snapshot/metadata fields are accepted.
    quantities: tuple[QuantityChange, ...] = ()
    remove_line_ids: tuple[int, ...] = ()
    add_items: tuple[ItemSelection, ...] = ()
    # None preserves allocations; () removes them while Pending.
    allocations: tuple[Allocation, ...] | None = None


@dataclass(frozen=True, slots=True)
class Correction:
    reason_code: str
    acknowledged: bool
    explanation: str | None = None


@dataclass(frozen=True, slots=True)
class OrderResult:
    order_id: int
    version: int
    is_received: bool
    total: Decimal


def _positive_int(value: int) -> int:
    if type(value) is not int or not 0 < value <= 2147483647:
        raise OrderError("Expected a positive integer within the database range")
    return value


def _id(value: int) -> int:
    if type(value) is not int or not 0 < value <= 9223372036854775807:
        raise OrderError("Invalid identifier")
    return value


def _money(value: Decimal, *, positive: bool = True) -> Decimal:
    if not isinstance(value, Decimal):
        raise OrderError("Money must be Decimal")
    try:
        Money().process_bind_param(value, None)
    except ValueError as exc:
        raise OrderError("Invalid monetary precision or range") from exc
    if value < 0 or (positive and value == 0):
        raise OrderError("Invalid monetary amount")
    return value


def _selections(items: tuple[ItemSelection, ...]) -> None:
    if type(items) is not tuple or any(type(i) is not ItemSelection for i in items):
        raise OrderError("Expected item selections")
    for item in items:
        _id(item.menu_item_id)
        _positive_int(item.quantity)


def _allocations(values: tuple[Allocation, ...]) -> dict[str, Decimal]:
    if type(values) is not tuple or any(type(a) is not Allocation for a in values):
        raise OrderError("Expected allocations")
    result: dict[str, Decimal] = {}
    for value in values:
        if not isinstance(value.category, str) or value.category not in PAYMENT_CODES:
            raise OrderError("Unknown payment category")
        amount = _money(value.amount)
        result[value.category] = _money(result.get(value.category, Decimal(0)) + amount)
    return dict(sorted(result.items()))


def _amount(value: Decimal) -> str:
    return format(value, ".2f")


def authorize_actor(session: Session, context: ActorContext, *, admin: bool = False) -> m.User:
    """Recheck the stored actor while holding authorization stable for the transaction."""
    if type(context) is not ActorContext:
        raise Forbidden("A trusted actor context is required")
    _id(context.user_id)
    user = session.scalar(select(m.User).where(m.User.id == context.user_id).with_for_update(read=True))
    roles = {"admin"} if admin else {"admin", "assistant_admin"}
    if user is None or not user.is_enabled or user.role_code not in roles:
        raise Forbidden("Actor is not authorized")
    return user


class OrderService:
    def __init__(self, session_factory: Callable[[], Session]):
        self._sessions = session_factory

    _actor = staticmethod(authorize_actor)

    @staticmethod
    def _order(session: Session, order_id: int, version: int) -> m.Order:
        _id(order_id)
        _positive_int(version)
        order = session.scalar(select(m.Order).where(m.Order.id == order_id).with_for_update())
        if order is None:
            raise NotFound("Order not found")
        if order.version != version:
            raise Conflict("Order changed; reload before retrying")
        return order

    @staticmethod
    def _offerings(session: Session, menu_id: int, items: tuple[ItemSelection, ...]) -> dict[int, m.MenuItem]:
        # Parent menu precedes sorted offerings, matching Stage 1 insert guards.
        if session.scalar(select(m.Menu).where(m.Menu.id == menu_id).with_for_update()) is None:
            raise NotFound("Menu not found")
        ids = sorted({i.menu_item_id for i in items})
        rows = session.scalars(select(m.MenuItem).where(m.MenuItem.id.in_(ids))
                               .order_by(m.MenuItem.id).with_for_update(read=True)).all()
        if len(rows) != len(ids) or any(row.menu_id != menu_id for row in rows):
            raise OrderError("Selected offering is outside the recorded menu")
        for row in rows:
            _money(row.unit_price, positive=False)
        return {row.id: row for row in rows}

    @staticmethod
    def _line(order_id: int, number: int, selection: ItemSelection, source: m.MenuItem) -> m.OrderItem:
        _money(source.unit_price * selection.quantity, positive=False)
        return m.OrderItem(order_id=order_id, line_number=number, source_menu_item_id=source.id,
                           item_name=source.item_name, category_code_snapshot=source.category_code,
                           unit_price=source.unit_price, quantity=selection.quantity)

    @staticmethod
    def _snapshot(session: Session, order: m.Order) -> dict:
        items = session.scalars(select(m.OrderItem).where(m.OrderItem.order_id == order.id)
                                .order_by(m.OrderItem.line_number)).all()
        allocations = session.scalars(select(m.PaymentAllocation).where(m.PaymentAllocation.order_id == order.id)
                                      .order_by(m.PaymentAllocation.payment_category_code)).all()
        return {
            "version": order.version, "is_received": order.is_received,
            "items": [{"id": i.id, "line_number": i.line_number, "source_menu_item_id": i.source_menu_item_id,
                       "name": i.item_name, "category": i.category_code_snapshot,
                       "unit_price": _amount(i.unit_price), "quantity": i.quantity,
                       "line_total": _amount(i.line_total)} for i in items],
            "allocations": [{"id": a.id, "category": a.payment_category_code, "amount": _amount(a.amount)}
                            for a in allocations],
        }

    @staticmethod
    def _result(order: m.Order, snapshot: dict) -> OrderResult:
        return OrderResult(order.id, order.version, order.is_received,
                           sum((Decimal(i["line_total"]) for i in snapshot["items"]), Decimal(0)))

    @staticmethod
    def _audit(session: Session, actor: m.User, order: m.Order, action: str,
               before: dict | None, after: dict, *, timestamp: datetime | None = None,
               reason: str | None = None) -> m.AuditEvent:
        event = m.AuditEvent(actor_user_id=actor.id, occurred_at=timestamp or datetime.now(timezone.utc),
                             action=action, entity_type="orders", entity_key=str(order.id),
                             before_values=before, after_values=after, reason=reason)
        session.add(event)
        session.flush()
        return event

    @staticmethod
    def _replace_allocations(session: Session, order: m.Order, amounts: dict[str, Decimal], actor: m.User) -> None:
        if order.visitor_id is not None and any(code != "finance" for code in amounts):
            raise OrderError("Visitor allocations must use Finance")
        existing = {a.payment_category_code: a for a in session.scalars(
            select(m.PaymentAllocation).where(m.PaymentAllocation.order_id == order.id))}
        now = datetime.now(timezone.utc)
        for code, allocation in existing.items():
            if code not in amounts:
                session.delete(allocation)
            elif allocation.amount != amounts[code]:
                allocation.amount = amounts[code]
                allocation.updated_by = actor.id
                allocation.updated_at = now
        for code, amount in amounts.items():
            if code not in existing:
                session.add(m.PaymentAllocation(order_id=order.id, payment_category_code=code,
                                                amount=amount, created_by=actor.id, updated_by=actor.id))

    def create_pending(self, context: ActorContext, request: CreateOrder) -> OrderResult:
        if type(request) is not CreateOrder or type(request.request_key) is not UUID:
            raise OrderError("Expected an order request with a UUID key")
        if type(request.service_date) is not date:
            raise OrderError("Expected a service date")
        _id(request.menu_id)
        if (request.employee_number is None) == (request.visitor_id is None):
            raise OrderError("Exactly one customer is required")
        if request.employee_number is not None and (not isinstance(request.employee_number, str)
                                                   or not request.employee_number.strip()):
            raise OrderError("Invalid employee identifier")
        if request.visitor_id is not None:
            _id(request.visitor_id)
        _selections(request.items)
        if not request.items:
            raise OrderError("An order requires an item")
        amounts = _allocations(request.allocations)
        original = {"service_date": request.service_date.isoformat(), "menu_id": request.menu_id,
                    "employee_number": request.employee_number, "visitor_id": request.visitor_id,
                    "items": [{"menu_item_id": i.menu_item_id, "quantity": i.quantity} for i in request.items],
                    "allocations": {code: _amount(amount) for code, amount in amounts.items()}}
        with self._sessions() as session, session.begin():
            actor = self._actor(session, context)
            # Serializes same-key requests before any menu/order locks. Hash
            # collisions merely serialize unrelated creates; UUID uniqueness remains.
            session.execute(text("SELECT pg_advisory_xact_lock(:key)"),
                            {"key": int.from_bytes(request.request_key.bytes[:8], signed=True)})
            existing = session.scalar(select(m.Order).where(m.Order.request_key == request.request_key).with_for_update())
            if existing is not None:
                event = session.scalar(select(m.AuditEvent).where(
                    m.AuditEvent.entity_type == "orders", m.AuditEvent.entity_key == str(existing.id),
                    m.AuditEvent.action == "order_created"))
                if (event is None or not isinstance(event.after_values, dict)
                        or event.after_values.get("request") != original):
                    raise Conflict("Request key already used for different contents")
                return self._result(existing, self._snapshot(session, existing))
            assignment = session.scalar(select(m.MenuDate).where(m.MenuDate.service_date == request.service_date)
                                        .with_for_update())
            if assignment is None or assignment.menu_id != request.menu_id:
                raise OrderError("Service date/menu assignment is invalid")
            sources = self._offerings(session, request.menu_id, request.items)
            if request.employee_number is not None:
                customer = session.scalar(select(m.Employee).where(m.Employee.employee_number == request.employee_number)
                                          .with_for_update(read=True))
            else:
                customer = session.scalar(select(m.Visitor).where(m.Visitor.id == request.visitor_id)
                                          .with_for_update(read=True))
            if customer is None:
                raise NotFound("Customer not found")
            employee = customer if isinstance(customer, m.Employee) else None
            order = m.Order(request_key=request.request_key, service_date=request.service_date, menu_id=request.menu_id,
                            created_by=actor.id, employee_number=request.employee_number, visitor_id=request.visitor_id,
                            customer_name_snapshot=employee.full_name if employee else customer.display_name,
                            position_snapshot=employee.position if employee else None,
                            campaign_snapshot=employee.campaign if employee else None,
                            line_of_business_snapshot=employee.line_of_business if employee else None)
            session.add(order)
            session.flush()
            for number, selection in enumerate(request.items, 1):
                session.add(self._line(order.id, number, selection, sources[selection.menu_item_id]))
            self._replace_allocations(session, order, amounts, actor)
            session.flush()
            snapshot = self._snapshot(session, order)
            self._audit(session, actor, order, "order_created", None, {"request": original, "order": snapshot})
            return self._result(order, snapshot)

    def edit_pending(self, context: ActorContext, order_id: int, expected_version: int,
                     changes: EditPending) -> OrderResult:
        if type(changes) is not EditPending:
            raise OrderError("Only approved Pending edit fields are accepted")
        _selections(changes.add_items)
        if type(changes.quantities) is not tuple or any(type(c) is not QuantityChange for c in changes.quantities):
            raise OrderError("Expected quantity changes")
        if type(changes.remove_line_ids) is not tuple:
            raise OrderError("Expected line identifiers")
        for change in changes.quantities:
            _id(change.line_id)
            _positive_int(change.quantity)
        for line_id in changes.remove_line_ids:
            _id(line_id)
        changed_ids = [c.line_id for c in changes.quantities]
        if (len(set(changed_ids)) != len(changed_ids)
                or len(set(changes.remove_line_ids)) != len(changes.remove_line_ids)
                or set(changed_ids) & set(changes.remove_line_ids)):
            raise OrderError("Conflicting line changes")
        amounts = None if changes.allocations is None else _allocations(changes.allocations)
        with self._sessions() as session, session.begin():
            actor = self._actor(session, context)
            order = self._order(session, order_id, expected_version)
            if order.is_received:
                raise Conflict("Reverse Received before editing")
            before = self._snapshot(session, order)
            lines = {i.id: i for i in session.scalars(select(m.OrderItem).where(m.OrderItem.order_id == order.id))}
            if not (set(changed_ids) | set(changes.remove_line_ids)) <= lines.keys():
                raise OrderError("Line does not belong to this order")
            if len(lines) - len(changes.remove_line_ids) + len(changes.add_items) < 1:
                raise OrderError("An order requires an item")
            sources = self._offerings(session, order.menu_id, changes.add_items) if changes.add_items else {}
            for change in changes.quantities:
                line = lines[change.line_id]
                _money(line.unit_price * change.quantity, positive=False)
                line.quantity = change.quantity
            for line_id in changes.remove_line_ids:
                session.delete(lines[line_id])
            number = max(i.line_number for i in lines.values())
            for selection in changes.add_items:
                number += 1
                session.add(self._line(order.id, number, selection, sources[selection.menu_item_id]))
            if amounts is not None:
                self._replace_allocations(session, order, amounts, actor)
            session.flush()
            after = self._snapshot(session, order)
            if before != after:
                order.version += 1
                session.flush()
                after["version"] = order.version
                self._audit(session, actor, order, "order_edited", before, after)
            return self._result(order, after)

    def mark_received(self, context: ActorContext, order_id: int, expected_version: int) -> OrderResult:
        return self._transition(context, order_id, expected_version, True, None)

    def reverse_received(self, context: ActorContext, order_id: int, expected_version: int,
                         correction: Correction) -> OrderResult:
        return self._transition(context, order_id, expected_version, False, correction)

    def _transition(self, context: ActorContext, order_id: int, expected_version: int,
                    received: bool, correction: Correction | None) -> OrderResult:
        with self._sessions() as session, session.begin():
            actor = self._actor(session, context, admin=not received)
            label = explanation = None
            if not received:
                if (type(correction) is not Correction or correction.acknowledged is not True
                        or not isinstance(correction.reason_code, str)
                        or correction.reason_code not in CORRECTION_REASONS):
                    raise OrderError("A configured reason and checked acknowledgement are required")
                if correction.explanation is not None and not isinstance(correction.explanation, str):
                    raise OrderError("Explanation must be text")
                explanation = correction.explanation.strip() if correction.explanation is not None else None
                if correction.reason_code == "other" and not explanation:
                    raise OrderError("Other requires a nonblank explanation")
                label = CORRECTION_REASONS[correction.reason_code]
            order = self._order(session, order_id, expected_version)
            before = self._snapshot(session, order)
            if order.is_received == received:
                return self._result(order, before)
            if received:
                if not before["items"] or not before["allocations"]:
                    raise OrderError("Received requires items and balanced allocations")
                total = self._result(order, before).total
                allocated = sum((Decimal(a["amount"]) for a in before["allocations"]), Decimal(0))
                if total != allocated:
                    raise OrderError("Allocations must equal the order total")
                for line in before["items"]:
                    _positive_int(line["quantity"])
                    _money(Decimal(line["unit_price"]), positive=False)
                    _money(Decimal(line["line_total"]), positive=False)
                for allocation in before["allocations"]:
                    if allocation["category"] not in PAYMENT_CODES:
                        raise OrderError("Unknown payment category")
                    _money(Decimal(allocation["amount"]))
                    if order.visitor_id is not None and allocation["category"] != "finance":
                        raise OrderError("Visitor allocations must use Finance")
            now = datetime.now(timezone.utc)
            order.is_received = received
            order.receipt_changed_by = actor.id
            order.receipt_changed_at = now
            order.version += 1
            session.flush()
            after = self._snapshot(session, order)
            if correction is not None:
                after["correction"] = {"code": correction.reason_code, "label": label,
                                       "explanation": explanation, "acknowledged": True}
            audit = self._audit(session, actor, order, "received_marked" if received else "received_reversed",
                                before, after, timestamp=now, reason=label)
            session.add(m.ReceiptEvent(audit_event_id=audit.id, order_id=order.id,
                                      from_received=not received, to_received=received,
                                      reason_code=correction.reason_code if correction else None,
                                      reason_label_snapshot=label, reason_explanation=explanation))
            session.flush()
            return self._result(order, after)
