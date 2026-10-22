"""Strict HTTP inputs and allowlisted business outputs; no persistence models."""

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StringConstraints, field_validator


Id = Annotated[int, Field(strict=True, gt=0, le=9223372036854775807)]
Count = Annotated[int, Field(strict=True, gt=0, le=2147483647)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
EmployeeNumber = Annotated[str, StringConstraints(min_length=1, max_length=200)]
Category = Literal["vegetable", "non_vegetable", "extra_rice"]
Payment = Literal["cash", "gcash", "sd", "incentive", "finance"]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="before")
    @classmethod
    def no_nul(cls, value):
        if isinstance(value, str) and "\x00" in value:
            raise ValueError("Invalid text")
        return value


class VisitorIn(Input):
    display_name: Name


class DishIn(Input):
    name: Name
    category_code: Category


class VisitorEdit(Input):
    display_name: Name
    expected_name: Name


class VisitorDelete(Input):
    expected_name: Name


class DishEdit(Input):
    name: Name
    category_code: Literal["vegetable", "non_vegetable"]
    expected_name: Name
    expected_category: Literal["vegetable", "non_vegetable"]


class DishDelete(Input):
    expected_name: Name
    expected_category: Literal["vegetable", "non_vegetable"]


class DateAssignment(Input):
    service_date: date
    # Required even when null: null asserts that the date is unassigned.
    expected_menu_id: Id | None


class ScheduleIn(Input):
    assignments: Annotated[list[DateAssignment], Field(min_length=1, max_length=366)]


class MenuDishChange(Input):
    id: Id
    expected_name: Name
    expected_category: Literal["vegetable", "non_vegetable"]
    delete: StrictBool = False
    name: Name | None = None
    category_code: Literal["vegetable", "non_vegetable"] | None = None


class MenuIn(Input):
    label: Name | None = None
    dish_ids: Annotated[list[Id], Field(max_length=100)]
    assignments: list[DateAssignment] = Field(default_factory=list, max_length=366)
    include_default_rice: StrictBool = False
    dish_changes: list[MenuDishChange] = Field(default_factory=list, max_length=100)


class MenuDefaultsOut(BaseModel):
    extra_rice_price: Decimal


class ItemIn(Input):
    menu_item_id: Id
    quantity: Count


class AllocationIn(Input):
    category: Payment
    amount: Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2)]

    @field_validator("amount", mode="before")
    @classmethod
    def exact_money(cls, value):
        if type(value) not in {str, int, Decimal}:
            raise ValueError("Use an exact decimal string or integer for money")
        return value


class OrderIn(Input):
    request_key: UUID
    service_date: date
    menu_id: Id
    employee_number: EmployeeNumber | None = None
    visitor_id: Id | None = None
    items: Annotated[list[ItemIn], Field(min_length=1, max_length=100)]
    allocations: list[AllocationIn] = Field(default_factory=list, max_length=100)


class QuantityIn(Input):
    line_id: Id
    quantity: Count


class VersionIn(Input):
    expected_version: Count


class EditIn(VersionIn):
    quantities: list[QuantityIn] = Field(default_factory=list, max_length=100)
    remove_line_ids: list[Id] = Field(default_factory=list, max_length=100)
    add_items: list[ItemIn] = Field(default_factory=list, max_length=100)
    allocations: Annotated[list[AllocationIn], Field(max_length=100)] | None = None


class ReversalIn(VersionIn):
    reason_code: Literal["mistaken_click", "incorrect_employee_marked", "incorrect_order_marked",
                         "incorrect_order_details", "other"]
    acknowledged: StrictBool
    explanation: Annotated[str, Field(max_length=2000)] | None = None


class EmployeeOut(BaseModel):
    employee_number: str
    full_name: str
    position: str | None
    campaign: str | None
    line_of_business: str | None


class VisitorOut(BaseModel):
    id: int
    display_name: str


class DishOut(BaseModel):
    id: int
    name: str
    category_code: Category
    is_active: bool


class OfferingOut(BaseModel):
    id: int
    dish_id: int
    item_name: str
    category_code: Category
    unit_price: Decimal


class MenuOut(BaseModel):
    id: int
    label: str | None
    items: list[OfferingOut]


class DatedMenuOut(MenuOut):
    service_date: date


class ScheduleOut(BaseModel):
    menu_id: int
    service_dates: list[date]


class ImportIssue(BaseModel):
    field: str
    code: str


class ImportRowError(BaseModel):
    row_number: int
    issues: list[ImportIssue]


class ImportOut(BaseModel):
    import_id: int
    status: str
    total_rows: int
    inserted_rows: int
    updated_rows: int
    unchanged_rows: int
    rejected_rows: int
    file_error_code: str | None
    errors: list[ImportRowError]
    errors_truncated: bool


class OrderSummary(BaseModel):
    order_id: int
    service_date: date
    menu_id: int
    employee_number: str | None
    visitor_id: int | None
    customer_name: str
    is_received: bool
    version: int
    total: Decimal


class OrderOverview(BaseModel):
    pending: int
    received: int
    total: int
    recognized_sales: Decimal


class OrderPage(BaseModel):
    revision: str
    orders: list[OrderSummary]


class LineOut(BaseModel):
    id: int
    line_number: int
    source_menu_item_id: int
    name: str
    category: Category
    unit_price: Decimal
    quantity: int
    line_total: Decimal


class AllocationOut(BaseModel):
    id: int
    category: Payment
    amount: Decimal


class OrderDetail(BaseModel):
    order_id: int
    service_date: date
    menu_id: int
    employee_number: str | None
    visitor_id: int | None
    customer_name: str
    position: str | None
    campaign: str | None
    line_of_business: str | None
    is_received: bool
    version: int
    items: list[LineOut]
    allocations: list[AllocationOut]
