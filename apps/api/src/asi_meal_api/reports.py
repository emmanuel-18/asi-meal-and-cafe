"""Operational reports over current Received orders, never payroll execution.

Every public read owns a PostgreSQL REPEATABLE READ, READ ONLY transaction.
Dates are explicit Philippine operational calendar dates, not timestamps. Actor
contexts must come from a future verified session provider, never request bodies.
"""

import calendar
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import case, func, select, text
from sqlalchemy.orm import Session

from asi_meal_api.db import models as m
from asi_meal_api.orders import ActorContext, Forbidden


ZERO = Decimal("0.00")
PAYMENT_CATEGORIES = ("cash", "gcash", "sd", "incentive", "finance")
ITEM_CATEGORIES = ("vegetable", "non_vegetable", "extra_rice")


class ReportInputError(ValueError):
    pass


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
            if user is None or not user.is_enabled or user.role_code not in {"admin", "assistant_admin"}:
                raise Forbidden("Actor may not view operational reports")
            yield session

    @staticmethod
    def _received(period: DateRange):
        return select(
            m.Order.id, m.Order.service_date, m.Order.employee_number,
            m.Order.customer_name_snapshot, m.Order.position_snapshot,
            m.Order.campaign_snapshot, m.Order.line_of_business_snapshot,
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

    def report_bundle(self, actor: ActorContext, period: DateRange) -> ReportBundle:
        """Use this call when all three reports must describe the same snapshot."""
        with self._snapshot(actor, period) as session:
            received = self._received(period)
            payments = self._payments(session, period, received)
            return ReportBundle(self._sales(session, period, received, payments), payments,
                                self._sd(session, period, received))
