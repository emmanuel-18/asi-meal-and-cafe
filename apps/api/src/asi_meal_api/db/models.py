"""Application mappings, including approved server-side authentication sessions."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Computed, Date, DateTime, ForeignKey,
    Identity, Index, Integer, LargeBinary, Text, UniqueConstraint, Uuid, func, text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from asi_meal_api.db.base import Base, Money


def nonblank(column: str) -> CheckConstraint:
    return CheckConstraint(f"btrim({column}) <> ''", name=f"{column}_nonblank")


def nonnegative_money(column: str) -> CheckConstraint:
    return CheckConstraint(
        f"{column} >= 0 AND {column} <> 'NaN'::numeric",
        name=f"{column}_valid",
    )


def fk(target: str):
    return ForeignKey(target, ondelete="RESTRICT", onupdate="RESTRICT")


class Identified:
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)


class Timestamps:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Role(Base):
    __tablename__ = "roles"
    __table_args__ = (
        CheckConstraint("code IN ('admin', 'assistant_admin')", name="code_allowed"),
        nonblank("display_name"),
    )
    code: Mapped[str] = mapped_column(Text, primary_key=True)
    display_name: Mapped[str] = mapped_column(Text)
    users: Mapped[list[User]] = relationship(back_populates="role", passive_deletes="all")


class User(Identified, Timestamps, Base):
    __tablename__ = "users"
    __table_args__ = (
        nonblank("login_name"), nonblank("display_name"), nonblank("password_hash"),
        Index("uq_users_login_normalized", func.lower(func.btrim(text("login_name"))), unique=True),
    )
    login_name: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(Text)
    password_hash: Mapped[str] = mapped_column(Text)
    role_code: Mapped[str] = mapped_column(fk("roles.code"))
    is_enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    role: Mapped[Role] = relationship(back_populates="users")


class AuthSession(Identified, Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (
        UniqueConstraint("token_hash"),
        CheckConstraint("octet_length(token_hash) = 32 AND octet_length(csrf_token) = 32", name="token_lengths"),
        CheckConstraint("isfinite(created_at) AND isfinite(last_seen_at) AND isfinite(expires_at) "
                        "AND (revoked_at IS NULL OR isfinite(revoked_at))", name="finite_times"),
        CheckConstraint("expires_at > created_at AND last_seen_at >= created_at AND last_seen_at <= expires_at "
                        "AND (revoked_at IS NULL OR revoked_at >= created_at)", name="time_order"),
        Index("ix_auth_sessions_user_id", "user_id"),
        Index("ix_auth_sessions_expires_at", "expires_at"),
    )
    user_id: Mapped[int] = mapped_column(fk("users.id"))
    token_hash: Mapped[bytes] = mapped_column(LargeBinary)
    csrf_token: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user: Mapped[User] = relationship()


class EmployeeImport(Identified, Base):
    __tablename__ = "employee_imports"
    __table_args__ = (
        CheckConstraint("status IN ('processing', 'completed', 'failed')", name="status_allowed"),
        CheckConstraint("source_sha256 ~ '^[0-9a-f]{64}$'", name="hash_format"),
        CheckConstraint("length(delimiter) = 1", name="delimiter_length"),
        CheckConstraint(
            "(status = 'processing' AND completed_at IS NULL) OR "
            "(status IN ('completed', 'failed') AND completed_at IS NOT NULL)",
            name="completion_metadata",
        ),
        CheckConstraint(
            "total_rows >= 0 AND inserted_rows >= 0 AND updated_rows >= 0 "
            "AND unchanged_rows >= 0 AND rejected_rows >= 0", name="counts_nonnegative",
        ),
        CheckConstraint(
            "status <> 'completed' OR total_rows = inserted_rows + updated_rows "
            "+ unchanged_rows + rejected_rows", name="completed_counts",
        ),
        nonblank("encoding"),
    )
    uploaded_by: Mapped[int] = mapped_column(fk("users.id"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_sha256: Mapped[str] = mapped_column(Text)
    encoding: Mapped[str] = mapped_column(Text)
    delimiter: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="processing")
    total_rows: Mapped[int] = mapped_column(Integer, server_default="0")
    inserted_rows: Mapped[int] = mapped_column(Integer, server_default="0")
    updated_rows: Mapped[int] = mapped_column(Integer, server_default="0")
    unchanged_rows: Mapped[int] = mapped_column(Integer, server_default="0")
    rejected_rows: Mapped[int] = mapped_column(Integer, server_default="0")
    file_error_code: Mapped[str | None] = mapped_column(Text)
    uploader: Mapped[User] = relationship()
    rows: Mapped[list[EmployeeImportRow]] = relationship(back_populates="import_job", passive_deletes="all")
    employees: Mapped[list[Employee]] = relationship(back_populates="last_import", passive_deletes="all")


class Employee(Timestamps, Base):
    __tablename__ = "employees"
    __table_args__ = (nonblank("employee_number"), nonblank("full_name"))
    employee_number: Mapped[str] = mapped_column(Text, primary_key=True)
    full_name: Mapped[str] = mapped_column(Text)
    position: Mapped[str | None] = mapped_column(Text)
    campaign: Mapped[str | None] = mapped_column(Text)
    line_of_business: Mapped[str | None] = mapped_column(Text)
    last_import_id: Mapped[int] = mapped_column(fk("employee_imports.id"))
    last_import: Mapped[EmployeeImport] = relationship(back_populates="employees")
    orders: Mapped[list[Order]] = relationship(back_populates="employee", passive_deletes="all")


class EmployeeImportRow(Identified, Base):
    __tablename__ = "employee_import_rows"
    __table_args__ = (
        UniqueConstraint("import_id", "row_number"),
        CheckConstraint("row_number > 0", name="row_positive"),
        CheckConstraint("outcome IN ('inserted','updated','unchanged','rejected')", name="outcome_allowed"),
    )
    import_id: Mapped[int] = mapped_column(fk("employee_imports.id"))
    row_number: Mapped[int] = mapped_column(Integer)
    employee_number: Mapped[str | None] = mapped_column(fk("employees.employee_number"))
    outcome: Mapped[str] = mapped_column(Text)
    issues: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    import_job: Mapped[EmployeeImport] = relationship(back_populates="rows")
    employee: Mapped[Employee | None] = relationship()


class Visitor(Identified, Timestamps, Base):
    __tablename__ = "visitors"
    __table_args__ = (nonblank("display_name"),)
    display_name: Mapped[str] = mapped_column(Text)
    created_by: Mapped[int] = mapped_column(fk("users.id"))
    creator: Mapped[User] = relationship()
    orders: Mapped[list[Order]] = relationship(back_populates="visitor", passive_deletes="all")


class ItemCategory(Base):
    __tablename__ = "item_categories"
    __table_args__ = (
        CheckConstraint("code IN ('vegetable','non_vegetable','extra_rice')", name="code_allowed"),
        nonblank("display_name"), nonnegative_money("default_unit_price"),
    )
    code: Mapped[str] = mapped_column(Text, primary_key=True)
    display_name: Mapped[str] = mapped_column(Text)
    default_unit_price: Mapped[Decimal] = mapped_column(Money())
    dishes: Mapped[list[Dish]] = relationship(back_populates="category", passive_deletes="all")
    offerings: Mapped[list[MenuItem]] = relationship(back_populates="category", passive_deletes="all")


class Dish(Identified, Timestamps, Base):
    __tablename__ = "dishes"
    __table_args__ = (nonblank("name"),)
    name: Mapped[str] = mapped_column(Text)
    category_code: Mapped[str] = mapped_column(fk("item_categories.code"))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    category: Mapped[ItemCategory] = relationship(back_populates="dishes")
    offerings: Mapped[list[MenuItem]] = relationship(back_populates="dish", passive_deletes="all")


class Menu(Identified, Timestamps, Base):
    __tablename__ = "menus"
    label: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int] = mapped_column(fk("users.id"))
    creator: Mapped[User] = relationship()
    dates: Mapped[list[MenuDate]] = relationship(back_populates="menu", passive_deletes="all")
    items: Mapped[list[MenuItem]] = relationship(back_populates="menu", passive_deletes="all")
    orders: Mapped[list[Order]] = relationship(back_populates="menu", passive_deletes="all")


class MenuDate(Base):
    __tablename__ = "menu_dates"
    __table_args__ = (Index("ix_menu_dates_menu_id", "menu_id"),)
    service_date: Mapped[date] = mapped_column(Date, primary_key=True)
    menu_id: Mapped[int] = mapped_column(fk("menus.id"))
    menu: Mapped[Menu] = relationship(back_populates="dates")
    orders: Mapped[list[Order]] = relationship(back_populates="menu_date", passive_deletes="all")


class MenuItem(Identified, Base):
    __tablename__ = "menu_items"
    __table_args__ = (
        UniqueConstraint("menu_id", "dish_id"), Index("ix_menu_items_dish_id", "dish_id"),
        nonblank("item_name"), nonnegative_money("unit_price"),
    )
    menu_id: Mapped[int] = mapped_column(fk("menus.id"))
    dish_id: Mapped[int] = mapped_column(fk("dishes.id"))
    item_name: Mapped[str] = mapped_column(Text)
    category_code: Mapped[str] = mapped_column(fk("item_categories.code"))
    unit_price: Mapped[Decimal] = mapped_column(Money())
    menu: Mapped[Menu] = relationship(back_populates="items")
    dish: Mapped[Dish] = relationship(back_populates="offerings")
    category: Mapped[ItemCategory] = relationship(back_populates="offerings")
    order_items: Mapped[list[OrderItem]] = relationship(back_populates="source_menu_item", passive_deletes="all")


class PaymentCategory(Base):
    __tablename__ = "payment_categories"
    __table_args__ = (
        CheckConstraint("code IN ('cash','gcash','sd','incentive','finance')", name="code_allowed"),
        nonblank("display_name"),
    )
    code: Mapped[str] = mapped_column(Text, primary_key=True)
    display_name: Mapped[str] = mapped_column(Text)
    allocations: Mapped[list[PaymentAllocation]] = relationship(back_populates="category", passive_deletes="all")


class Order(Identified, Base):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("request_key"),
        CheckConstraint("(employee_number IS NOT NULL) <> (visitor_id IS NOT NULL)", name="customer_xor"),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint(
            "(receipt_changed_by IS NULL) = (receipt_changed_at IS NULL) "
            "AND (NOT is_received OR receipt_changed_by IS NOT NULL)", name="receipt_metadata",
        ),
        nonblank("customer_name_snapshot"),
        Index("ix_orders_received_date", "service_date", "id", postgresql_where=text("is_received")),
        Index("ix_orders_employee_date", "employee_number", "service_date", postgresql_where=text("employee_number IS NOT NULL")),
        Index("ix_orders_visitor_date", "visitor_id", "service_date", postgresql_where=text("visitor_id IS NOT NULL")),
    )
    request_key: Mapped[UUID] = mapped_column(Uuid)
    service_date: Mapped[date] = mapped_column(fk("menu_dates.service_date"))
    menu_id: Mapped[int] = mapped_column(fk("menus.id"))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[int] = mapped_column(fk("users.id"))
    employee_number: Mapped[str | None] = mapped_column(fk("employees.employee_number"))
    visitor_id: Mapped[int | None] = mapped_column(fk("visitors.id"))
    customer_name_snapshot: Mapped[str] = mapped_column(Text)
    position_snapshot: Mapped[str | None] = mapped_column(Text)
    campaign_snapshot: Mapped[str | None] = mapped_column(Text)
    line_of_business_snapshot: Mapped[str | None] = mapped_column(Text)
    is_received: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    receipt_changed_by: Mapped[int | None] = mapped_column(fk("users.id"))
    receipt_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, server_default="1")
    creator: Mapped[User] = relationship(foreign_keys=[created_by])
    receipt_actor: Mapped[User | None] = relationship(foreign_keys=[receipt_changed_by])
    employee: Mapped[Employee | None] = relationship(back_populates="orders")
    visitor: Mapped[Visitor | None] = relationship(back_populates="orders")
    menu: Mapped[Menu] = relationship(back_populates="orders")
    menu_date: Mapped[MenuDate] = relationship(back_populates="orders")
    items: Mapped[list[OrderItem]] = relationship(back_populates="order", passive_deletes="all")
    allocations: Mapped[list[PaymentAllocation]] = relationship(back_populates="order", passive_deletes="all")
    receipt_events: Mapped[list[ReceiptEvent]] = relationship(back_populates="order", passive_deletes="all")
    __mapper_args__ = {"version_id_col": version}


class OrderItem(Identified, Base):
    __tablename__ = "order_items"
    __table_args__ = (
        UniqueConstraint("order_id", "line_number"),
        CheckConstraint("line_number > 0 AND quantity > 0", name="positive_counts"),
        CheckConstraint("category_code_snapshot IN ('vegetable','non_vegetable','extra_rice')", name="snapshot_category"),
        nonblank("item_name"), nonnegative_money("unit_price"),
    )
    order_id: Mapped[int] = mapped_column(fk("orders.id"))
    line_number: Mapped[int] = mapped_column(Integer)
    source_menu_item_id: Mapped[int] = mapped_column(fk("menu_items.id"))
    item_name: Mapped[str] = mapped_column(Text)
    category_code_snapshot: Mapped[str] = mapped_column(Text)
    unit_price: Mapped[Decimal] = mapped_column(Money())
    quantity: Mapped[int] = mapped_column(Integer)
    line_total: Mapped[Decimal] = mapped_column(Money(), Computed("unit_price * quantity::numeric", persisted=True))
    order: Mapped[Order] = relationship(back_populates="items")
    source_menu_item: Mapped[MenuItem] = relationship(back_populates="order_items")


class PaymentAllocation(Identified, Base):
    __tablename__ = "payment_allocations"
    __table_args__ = (
        UniqueConstraint("order_id", "payment_category_code"),
        CheckConstraint("amount > 0 AND amount <> 'NaN'::numeric", name="amount_positive"),
    )
    order_id: Mapped[int] = mapped_column(fk("orders.id"))
    payment_category_code: Mapped[str] = mapped_column(fk("payment_categories.code"))
    amount: Mapped[Decimal] = mapped_column(Money())
    created_by: Mapped[int] = mapped_column(fk("users.id"))
    updated_by: Mapped[int] = mapped_column(fk("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    order: Mapped[Order] = relationship(back_populates="allocations")
    category: Mapped[PaymentCategory] = relationship(back_populates="allocations")
    creator: Mapped[User] = relationship(foreign_keys=[created_by])
    updater: Mapped[User] = relationship(foreign_keys=[updated_by])


class AuditEvent(Identified, Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        nonblank("action"), nonblank("entity_type"), nonblank("entity_key"),
        Index("ix_audit_events_entity_time", "entity_type", "entity_key", "occurred_at"),
    )
    actor_user_id: Mapped[int] = mapped_column(fk("users.id"))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    action: Mapped[str] = mapped_column(Text)
    entity_type: Mapped[str] = mapped_column(Text)
    entity_key: Mapped[str] = mapped_column(Text)
    before_values: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after_values: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    reason: Mapped[str | None] = mapped_column(Text)
    actor: Mapped[User] = relationship()
    receipt_event: Mapped[ReceiptEvent | None] = relationship(back_populates="audit_event", passive_deletes="all")


class ReceiptEvent(Base):
    __tablename__ = "receipt_events"
    __table_args__ = (
        CheckConstraint("from_received <> to_received", name="state_changes"),
        CheckConstraint(
            "(reason_code IS NULL AND reason_label_snapshot IS NULL AND reason_explanation IS NULL) OR "
            "(reason_code IS NOT NULL AND btrim(reason_code) <> '' AND "
            "reason_label_snapshot IS NOT NULL AND btrim(reason_label_snapshot) <> '')",
            name="reason_metadata",
        ),
        CheckConstraint("NOT from_received OR reason_code IS NOT NULL", name="reversal_reason_required"),
        CheckConstraint(
            "reason_code IS DISTINCT FROM 'other' OR "
            "(reason_explanation IS NOT NULL AND reason_explanation ~ '[^[:space:]]')",
            name="other_explanation",
        ),
        Index("ix_receipt_events_order_event", "order_id", "audit_event_id"),
    )
    audit_event_id: Mapped[int] = mapped_column(fk("audit_events.id"), primary_key=True)
    order_id: Mapped[int] = mapped_column(fk("orders.id"))
    from_received: Mapped[bool] = mapped_column(Boolean)
    to_received: Mapped[bool] = mapped_column(Boolean)
    reason_code: Mapped[str | None] = mapped_column(Text)
    reason_label_snapshot: Mapped[str | None] = mapped_column(Text)
    reason_explanation: Mapped[str | None] = mapped_column(Text)
    order: Mapped[Order] = relationship(back_populates="receipt_events")
    audit_event: Mapped[AuditEvent] = relationship(back_populates="receipt_event")
