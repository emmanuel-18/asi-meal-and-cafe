"""Operational reports over current Received orders, never payroll execution.

Every public read owns a PostgreSQL REPEATABLE READ, READ ONLY transaction.
Dates are explicit Philippine operational calendar dates, not timestamps. Actor
contexts come from verified server-side sessions, never request bodies.
"""

import calendar
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from sqlalchemy import case, func, select, text
from sqlalchemy.orm import Session

from asi_meal_api.db import models as m
from asi_meal_api.orders import ActorContext, Forbidden


ZERO = Decimal("0.00")
PAYMENT_CATEGORIES = ("cash", "gcash", "sd", "incentive", "finance")
ITEM_CATEGORIES = ("vegetable", "non_vegetable", "extra_rice")
MAX_EXPORT_DAYS = 3660


class ReportInputError(ValueError):
    pass


class ReportReconciliationError(RuntimeError):
    """A detailed report cannot safely be reconciled; never contains personal data."""


@dataclass(frozen=True, slots=True)
class DateRange:
    start: date
    end: date

    def __post_init__(self):
        if type(self.start) is not date or type(self.end) is not date or self.end < self.start:
            raise ReportInputError("Expected valid inclusive calendar dates in ascending order")

    @classmethod
    def daily(cls, day: date) -> "DateRange":
        return cls(day, day)

    @classmethod
    def weekly(cls, containing_date: date) -> "DateRange":
        if type(containing_date) is not date:
            raise ReportInputError("Expected a calendar date")
        try:
            start = containing_date - timedelta(days=containing_date.weekday())
            return cls(start, start + timedelta(days=6))
        except OverflowError:
            raise ReportInputError("Week exceeds supported calendar dates") from None

    @classmethod
    def monthly(cls, year: int, month: int) -> "DateRange":
        if type(year) is not int or type(month) is not int:
            raise ReportInputError("Expected an integer year and month")
        try:
            return cls(date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1]))
        except ValueError:
            raise ReportInputError("Invalid calendar month") from None


@dataclass(frozen=True, slots=True)
class PaymentTotal:
    category: str
    amount: Decimal


@dataclass(frozen=True, slots=True)
class PaymentSummary:
    period: DateRange
    totals: tuple[PaymentTotal, ...]
    total: Decimal


@dataclass(frozen=True, slots=True)
class ItemTotal:
    source_menu_item_id: int
    item_name: str
    category: str
    unit_price: Decimal
    quantity: int
    amount: Decimal


@dataclass(frozen=True, slots=True)
class CategoryTotal:
    category: str
    quantity: int
    amount: Decimal


@dataclass(frozen=True, slots=True)
class SalesSummary:
    period: DateRange
    recognized_sales: Decimal
    received_order_count: int
    item_quantity: int
    meal_quantity: int
    items: tuple[ItemTotal, ...]
    categories: tuple[CategoryTotal, ...]
    payments: tuple[PaymentTotal, ...]
    allocated_total: Decimal
    allocation_difference: Decimal

    @property
    def reconciles(self) -> bool:
        # Mathematical consistency only; no external payment verification.
        return self.allocation_difference == ZERO


@dataclass(frozen=True, slots=True)
class SDOrder:
    order_id: int
    service_date: date
    employee_number: str
    customer_name: str
    position: str | None
    campaign: str | None
    line_of_business: str | None
    sd_amount: Decimal


@dataclass(frozen=True, slots=True)
class EmployeeSDTotal:
    employee_number: str
    order_count: int
    sd_amount: Decimal


@dataclass(frozen=True, slots=True)
class SalaryDeductionReport:
    period: DateRange
    employees: tuple[EmployeeSDTotal, ...]
    orders: tuple[SDOrder, ...]
    total: Decimal


@dataclass(frozen=True, slots=True)
class ReportBundle:
    sales: SalesSummary
    payments: PaymentSummary
    salary_deduction: SalaryDeductionReport


@dataclass(frozen=True, slots=True)
class ExportItem:
    order_item_id: int
    line_number: int
    source_menu_item_id: int
    item_name: str
    category: str
    unit_price: Decimal
    quantity: int
    line_total: Decimal


@dataclass(frozen=True, slots=True)
class ExportOrder:
    order_id: int
    service_date: date
    menu_id: int
    customer_type: Literal["employee", "visitor"]
    employee_number: str | None
    visitor_id: int | None
    customer_name: str
    position: str | None
    campaign: str | None
    line_of_business: str | None
    items: tuple[ExportItem, ...]
    allocations: tuple[PaymentTotal, ...]
    total: Decimal


@dataclass(frozen=True, slots=True)
class ExportOffering:
    menu_item_id: int
    dish_id: int
    item_name: str
    category: str
    unit_price: Decimal


@dataclass(frozen=True, slots=True)
class ExportMenu:
    menu_id: int
    offerings: tuple[ExportOffering, ...]


@dataclass(frozen=True, slots=True)
class ExportMenuDate:
    service_date: date
    assigned_menu_id: int | None
    recorded_menu_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class ExportDaily:
    service_date: date
    recognized_sales: Decimal
    received_order_count: int
    meal_quantity: int
    item_quantity: int
    payments: tuple[PaymentTotal, ...]
    allocated_total: Decimal
    allocation_difference: Decimal


@dataclass(frozen=True, slots=True)
class ExportSDCampaign:
    campaign: str | None
    sd_amount: Decimal


@dataclass(frozen=True, slots=True)
class ExportDetails:
    period: DateRange
    orders: tuple[ExportOrder, ...]
    menu_dates: tuple[ExportMenuDate, ...]
    menus: tuple[ExportMenu, ...]
    daily: tuple[ExportDaily, ...]
    sd_campaigns: tuple[ExportSDCampaign, ...]


@dataclass(frozen=True, slots=True)
class ExportReportBundle(ReportBundle):
    export_details: ExportDetails


def _reconcile(condition: bool):
    if not condition:
        raise ReportReconciliationError("Report data could not be reconciled")


def _centavos(amount: Decimal) -> int:
    _reconcile(isinstance(amount, Decimal) and amount.is_finite() and amount >= ZERO)
    numerator, denominator = amount.as_integer_ratio()
    cents, remainder = divmod(numerator * 100, denominator)
    _reconcile(remainder == 0)
    return cents


def _from_centavos(cents: int) -> Decimal:
    absolute = abs(cents)
    return Decimal(f"{'-' if cents < 0 else ''}{absolute // 100}.{absolute % 100:02d}")


class ReportingService:
    def __init__(self, session_factory: Callable[[], Session]):
        self._sessions = session_factory

    @contextmanager
    def _snapshot(self, actor: ActorContext, period: DateRange) -> Iterator[Session]:
        if type(period) is not DateRange:
            raise ReportInputError("Expected a validated date range")
        if (type(actor) is not ActorContext or type(actor.user_id) is not int
                or not 0 < actor.user_id <= 9223372036854775807):
            raise Forbidden("A trusted report actor context is required")
        with self._sessions() as session, session.begin():
            # Must be an independent fresh Session bound to an Engine, rather
            # than a borrowed connection already inside a caller transaction.
            session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            session.execute(text("SET TRANSACTION READ ONLY"))
            user = session.scalar(select(m.User).where(m.User.id == actor.user_id))
            if user is None or not user.is_enabled or user.password_change_required or user.role_code not in {"admin", "assistant_admin", "super_admin"}:
                raise Forbidden("Actor may not view operational reports")
            yield session

    @staticmethod
    def _received(period: DateRange):
        return select(
            m.Order.id, m.Order.service_date, m.Order.employee_number,
            m.Order.customer_name_snapshot, m.Order.position_snapshot,
            m.Order.campaign_snapshot, m.Order.line_of_business_snapshot,
            m.Order.visitor_id, m.Order.menu_id,
        ).where(m.Order.is_received.is_(True), m.Order.service_date >= period.start,
                m.Order.service_date <= period.end).cte("received_orders")

    @staticmethod
    def _payments(session: Session, period: DateRange, received) -> PaymentSummary:
        # No item table participates in this aggregation.
        amounts = dict(session.execute(select(m.PaymentAllocation.payment_category_code,
            func.sum(m.PaymentAllocation.amount)).join(received, received.c.id == m.PaymentAllocation.order_id)
            .group_by(m.PaymentAllocation.payment_category_code)).all())
        totals = tuple(PaymentTotal(code, amounts.get(code, ZERO)) for code in PAYMENT_CATEGORIES)
        return PaymentSummary(period, totals, sum((row.amount for row in totals), ZERO))

    @staticmethod
    def _sales(session: Session, period: DateRange, received, payments: PaymentSummary) -> SalesSummary:
        # Aggregate items per order first, so counting orders cannot count lines.
        # Payment aggregates are combined in Python, never joined to raw items.
        per_order = select(m.OrderItem.order_id.label("order_id"),
            func.sum(m.OrderItem.line_total).label("amount"),
            func.sum(m.OrderItem.quantity).label("quantity"),
            func.sum(case((m.OrderItem.category_code_snapshot.in_(("vegetable", "non_vegetable")),
                           m.OrderItem.quantity), else_=0)).label("meals"))
        per_order = per_order.join(received, received.c.id == m.OrderItem.order_id)
        per_order = per_order.group_by(m.OrderItem.order_id).cte("items_per_order")
        totals = session.execute(select(func.count(received.c.id),
            func.coalesce(func.sum(per_order.c.amount), ZERO),
            func.coalesce(func.sum(per_order.c.quantity), 0),
            func.coalesce(func.sum(per_order.c.meals), 0))
            .select_from(received.outerjoin(per_order, received.c.id == per_order.c.order_id))).one()
        columns = (m.OrderItem.source_menu_item_id, m.OrderItem.item_name,
                   m.OrderItem.category_code_snapshot, m.OrderItem.unit_price)
        rows = session.execute(select(*columns, func.sum(m.OrderItem.quantity), func.sum(m.OrderItem.line_total))
            .join(received, received.c.id == m.OrderItem.order_id).group_by(*columns).order_by(*columns)).all()
        items = tuple(ItemTotal(source, name, category, price, int(quantity), amount)
                      for source, name, category, price, quantity, amount in rows)
        categories = tuple(CategoryTotal(code, sum(i.quantity for i in items if i.category == code),
            sum((i.amount for i in items if i.category == code), ZERO)) for code in ITEM_CATEGORIES)
        return SalesSummary(period, totals[1], int(totals[0]), int(totals[2]), int(totals[3]),
                            items, categories, payments.totals, payments.total, totals[1] - payments.total)

    @staticmethod
    def _sd(session: Session, period: DateRange, received) -> SalaryDeductionReport:
        rows = session.execute(select(received.c.id, received.c.service_date, received.c.employee_number,
            received.c.customer_name_snapshot, received.c.position_snapshot, received.c.campaign_snapshot,
            received.c.line_of_business_snapshot, m.PaymentAllocation.amount)
            .join(m.PaymentAllocation, m.PaymentAllocation.order_id == received.c.id)
            .where(m.PaymentAllocation.payment_category_code == "sd", received.c.employee_number.is_not(None))
            .order_by(received.c.employee_number, received.c.service_date, received.c.id)).all()
        orders = tuple(SDOrder(*row) for row in rows)
        amounts: dict[str, Decimal] = {}
        counts: dict[str, int] = {}
        for order in orders:
            amounts[order.employee_number] = amounts.get(order.employee_number, ZERO) + order.sd_amount
            counts[order.employee_number] = counts.get(order.employee_number, 0) + 1
        employees = tuple(EmployeeSDTotal(number, counts[number], amount) for number, amount in sorted(amounts.items()))
        return SalaryDeductionReport(period, employees, orders, sum(amounts.values(), ZERO))

    def sales_summary(self, actor: ActorContext, period: DateRange) -> SalesSummary:
        with self._snapshot(actor, period) as session:
            received = self._received(period)
            return self._sales(session, period, received, self._payments(session, period, received))

    def payment_summary(self, actor: ActorContext, period: DateRange) -> PaymentSummary:
        with self._snapshot(actor, period) as session:
            return self._payments(session, period, self._received(period))

    def salary_deduction_report(self, actor: ActorContext, period: DateRange) -> SalaryDeductionReport:
        with self._snapshot(actor, period) as session:
            return self._sd(session, period, self._received(period))

    @staticmethod
    def _export_details(session: Session, period: DateRange, received,
                        sales: SalesSummary, payments: PaymentSummary,
                        sd: SalaryDeductionReport) -> ExportDetails:
        days = (period.end - period.start).days + 1
        if days > MAX_EXPORT_DAYS:
            raise ReportInputError(f"Export details support at most {MAX_EXPORT_DAYS} inclusive dates; choose a shorter period")

        # Five batched reads, independent of order count; no HRMS/customer joins,
        # no pagination, and no raw item-to-allocation fan-out.
        records = session.execute(select(received).order_by(received.c.service_date, received.c.id)).mappings().all()
        items: dict[int, list[ExportItem]] = {}
        for row in session.execute(select(
            m.OrderItem.order_id, m.OrderItem.id, m.OrderItem.line_number,
            m.OrderItem.source_menu_item_id, m.OrderItem.item_name,
            m.OrderItem.category_code_snapshot, m.OrderItem.unit_price,
            m.OrderItem.quantity, m.OrderItem.line_total,
        ).join(received, received.c.id == m.OrderItem.order_id)
                .order_by(m.OrderItem.order_id, m.OrderItem.line_number)):
            items.setdefault(row[0], []).append(ExportItem(*row[1:]))
        allocations: dict[int, dict[str, Decimal]] = {}
        for order_id, category, amount in session.execute(select(
            m.PaymentAllocation.order_id, m.PaymentAllocation.payment_category_code,
            m.PaymentAllocation.amount,
        ).join(received, received.c.id == m.PaymentAllocation.order_id)):
            values = allocations.setdefault(order_id, {})
            _reconcile(category in PAYMENT_CATEGORIES and category not in values and _centavos(amount) > 0)
            values[category] = amount

        assigned = dict(session.execute(select(m.MenuDate.service_date, m.MenuDate.menu_id)
            .where(m.MenuDate.service_date >= period.start, m.MenuDate.service_date <= period.end)).all())
        relevant_menus = select(m.MenuDate.menu_id).where(
            m.MenuDate.service_date >= period.start, m.MenuDate.service_date <= period.end,
        ).union(select(received.c.menu_id))
        offerings: dict[int, list[ExportOffering]] = {}
        for row in session.execute(select(
            m.MenuItem.menu_id, m.MenuItem.id, m.MenuItem.dish_id,
            m.MenuItem.item_name, m.MenuItem.category_code, m.MenuItem.unit_price,
        ).where(m.MenuItem.menu_id.in_(relevant_menus)).order_by(m.MenuItem.menu_id, m.MenuItem.id)):
            offerings.setdefault(row[0], []).append(ExportOffering(*row[1:]))

        orders = []
        by_day: dict[date, list[ExportOrder]] = {}
        item_totals: dict[tuple, tuple[int, int]] = {}
        category_totals = {code: (0, 0) for code in ITEM_CATEGORIES}
        payment_totals = dict.fromkeys(PAYMENT_CATEGORIES, 0)
        campaigns: dict[str | None, int] = {}
        sd_orders = []
        sd_employees: dict[str, tuple[int, int]] = {}
        for record in records:
            order_id = record["id"]
            lines = tuple(items.get(order_id, ()))
            amounts = allocations.get(order_id, {})
            _reconcile(bool(lines) and bool(amounts))
            total = 0
            for line in lines:
                _reconcile(line.category in ITEM_CATEGORIES and line.quantity > 0)
                value = _centavos(line.line_total)
                _reconcile(value == _centavos(line.unit_price) * line.quantity)
                total += value
                key = (line.source_menu_item_id, line.item_name, line.category, line.unit_price)
                quantity, amount = item_totals.get(key, (0, 0))
                item_totals[key] = (quantity + line.quantity, amount + value)
                quantity, amount = category_totals[line.category]
                category_totals[line.category] = (quantity + line.quantity, amount + value)
            _reconcile(total == sum(_centavos(amount) for amount in amounts.values()))
            employee = record["employee_number"]
            visitor = record["visitor_id"]
            _reconcile((employee is not None) != (visitor is not None))
            if visitor is not None:
                _reconcile(set(amounts) == {"finance"})
            order = ExportOrder(
                order_id, record["service_date"], record["menu_id"],
                "employee" if employee is not None else "visitor", employee, visitor,
                record["customer_name_snapshot"], record["position_snapshot"],
                record["campaign_snapshot"], record["line_of_business_snapshot"], lines,
                tuple(PaymentTotal(code, amounts[code]) for code in PAYMENT_CATEGORIES if code in amounts),
                _from_centavos(total),
            )
            orders.append(order)
            by_day.setdefault(order.service_date, []).append(order)
            for code, amount in amounts.items():
                payment_totals[code] += _centavos(amount)
            if "sd" in amounts:
                _reconcile(employee is not None)
                sd_amount = amounts["sd"]
                sd_orders.append(SDOrder(order_id, order.service_date, employee, order.customer_name,
                                        order.position, order.campaign, order.line_of_business, sd_amount))
                count, amount = sd_employees.get(employee, (0, 0))
                sd_employees[employee] = (count + 1, amount + _centavos(sd_amount))
                campaigns[order.campaign] = campaigns.get(order.campaign, 0) + _centavos(sd_amount)

        # Independently compare every detailed grouping to existing SQL reports.
        _reconcile(len(orders) == sales.received_order_count)
        _reconcile(sum(_centavos(order.total) for order in orders) == _centavos(sales.recognized_sales))
        _reconcile(item_totals == {(i.source_menu_item_id, i.item_name, i.category, i.unit_price):
                                  (i.quantity, _centavos(i.amount)) for i in sales.items})
        _reconcile(category_totals == {i.category: (i.quantity, _centavos(i.amount)) for i in sales.categories})
        _reconcile(sum(value[0] for value in category_totals.values()) == sales.item_quantity)
        _reconcile(sum(category_totals[code][0] for code in ("vegetable", "non_vegetable")) == sales.meal_quantity)
        _reconcile(payment_totals == {i.category: _centavos(i.amount) for i in payments.totals})
        _reconcile(payment_totals == {i.category: _centavos(i.amount) for i in sales.payments})
        _reconcile(sum(payment_totals.values()) == _centavos(payments.total) == _centavos(sales.allocated_total)
                   == _centavos(sales.recognized_sales) and sales.allocation_difference == ZERO)
        _reconcile(sorted(sd_orders, key=lambda o: (o.employee_number, o.service_date, o.order_id)) == list(sd.orders))
        _reconcile(sd_employees == {i.employee_number: (i.order_count, _centavos(i.sd_amount)) for i in sd.employees})
        _reconcile(sum(campaigns.values()) == payment_totals["sd"] == _centavos(sd.total))

        daily = []
        menu_dates = []
        for offset in range(days):
            day = period.start + timedelta(days=offset)
            day_orders = by_day.get(day, ())
            day_payments = dict.fromkeys(PAYMENT_CATEGORIES, 0)
            for order in day_orders:
                for allocation in order.allocations:
                    day_payments[allocation.category] += _centavos(allocation.amount)
            total = sum(_centavos(order.total) for order in day_orders)
            allocated = sum(day_payments.values())
            _reconcile(total == allocated)
            daily.append(ExportDaily(day, _from_centavos(total), len(day_orders),
                sum(i.quantity for o in day_orders for i in o.items if i.category != "extra_rice"),
                sum(i.quantity for o in day_orders for i in o.items),
                tuple(PaymentTotal(code, _from_centavos(day_payments[code])) for code in PAYMENT_CATEGORIES),
                _from_centavos(allocated), _from_centavos(total - allocated)))
            menu_dates.append(ExportMenuDate(day, assigned.get(day), tuple(sorted({o.menu_id for o in day_orders}))))
        return ExportDetails(period, tuple(orders), tuple(menu_dates),
            tuple(ExportMenu(menu_id, tuple(offerings.get(menu_id, ())))
                  for menu_id in sorted(set(assigned.values()) | {o.menu_id for o in orders})),
            tuple(daily), tuple(ExportSDCampaign(campaign, _from_centavos(amount))
                for campaign, amount in sorted(campaigns.items(), key=lambda value: (value[0] is not None, value[0] or ""))))

    def report_bundle(self, actor: ActorContext, period: DateRange, *,
                      include_export_details: bool = False) -> ReportBundle | ExportReportBundle:
        """Use this call when all three reports must describe the same snapshot."""
        with self._snapshot(actor, period) as session:
            received = self._received(period)
            payments = self._payments(session, period, received)
            sales = self._sales(session, period, received, payments)
            sd = self._sd(session, period, received)
            if include_export_details:
                details = self._export_details(session, period, received, sales, payments, sd)
                return ExportReportBundle(sales, payments, sd, details)
            return ReportBundle(sales, payments, sd)
