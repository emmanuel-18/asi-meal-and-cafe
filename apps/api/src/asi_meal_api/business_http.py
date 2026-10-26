"""Protected business adapters. Services own authorization and transactions."""

from dataclasses import asdict
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from asi_meal_api.auth_http import admin_actor, authenticated_actor, runtime
from asi_meal_api import business_schemas as s
from asi_meal_api.business_services import BusinessService
from asi_meal_api.employee_imports import EmployeeImportService
from asi_meal_api.orders import ActorContext, Allocation, Correction, CreateOrder, EditPending, ItemSelection, OrderResult, OrderService, QuantityChange
from asi_meal_api.reports import DateRange, ExportReportBundle, PaymentSummary, ReportBundle, ReportInputError, ReportingService, SalaryDeductionReport, SalesSummary


Actor = Annotated[ActorContext, Depends(authenticated_actor)]
Admin = Annotated[ActorContext, Depends(admin_actor)]
ResourceId = Annotated[int, Path(gt=0, le=9223372036854775807)]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0, le=10000)]
Search = Annotated[str, Query(max_length=100, pattern=r"^[^\x00]*$")]


def services(request: Request):
    return runtime(request).service.session_factory


def directory(request: Request):
    return BusinessService(services(request))


def selections(values):
    return tuple(ItemSelection(i.menu_item_id, i.quantity) for i in values)


def allocations(values):
    return tuple(Allocation(a.category, a.amount) for a in values)


def assignments(values):
    return [(a.service_date, a.expected_menu_id) for a in values]


directory_router = APIRouter(prefix="/api", tags=["Directories"])
menu_router = APIRouter(prefix="/api", tags=["Menus"])
order_router = APIRouter(prefix="/api/orders", tags=["Orders"])
report_router = APIRouter(prefix="/api/reports", tags=["Reports"])


@directory_router.get("/employees", response_model=list[s.EmployeeOut])
def employees(request: Request, actor: Actor, q: Search = "", limit: Limit = 20, offset: Offset = 0):
    return directory(request).employees(actor, q, limit, offset)


@directory_router.post("/employees/import", response_model=s.ImportOut, openapi_extra={
    "requestBody": {"required": True, "content": {"text/csv": {"schema": {"type": "string", "format": "binary"}}}}})
async def import_employees(request: Request, actor: Admin):
    """Raw UTF-8 CSV body (text/csv), not multipart; no filename or disk storage."""
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "text/csv":
        raise HTTPException(415, "Expected a text/csv upload")
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > 8 * 1024 * 1024:
            raise HTTPException(413, "CSV exceeds the 8 MiB upload limit")
        data.extend(chunk)
    factory = services(request)
    result = await run_in_threadpool(EmployeeImportService(factory).import_csv, actor, bytes(data))
    errors = await run_in_threadpool(BusinessService(factory).import_errors, actor, result.import_id)
    # A failed validated batch is a recorded import outcome, not HTTP success.
    payload = s.ImportOut(**asdict(result), **errors)
    return JSONResponse(payload.model_dump(mode="json"), status_code=200 if result.status == "completed" else 422)


@directory_router.get("/visitors", response_model=list[s.VisitorOut])
def visitors(request: Request, actor: Actor, q: Search = "", limit: Limit = 20, offset: Offset = 0):
    return directory(request).visitors(actor, q, limit, offset)


@directory_router.post("/visitors", response_model=s.VisitorOut, status_code=201)
def create_visitor(body: s.VisitorIn, request: Request, actor: Actor):
    return directory(request).create_visitor(actor, body.display_name)


@directory_router.patch("/visitors/{visitor_id}", response_model=s.VisitorOut)
def edit_visitor(visitor_id: ResourceId, body: s.VisitorEdit, request: Request, actor: Actor):
    return directory(request).change_visitor(actor, visitor_id, body.expected_name, body.display_name)


@directory_router.delete("/visitors/{visitor_id}", status_code=204)
def delete_visitor(visitor_id: ResourceId, body: s.VisitorDelete, request: Request, actor: Actor):
    directory(request).change_visitor(actor, visitor_id, body.expected_name)


@menu_router.get("/dishes", response_model=list[s.DishOut])
def dishes(request: Request, actor: Actor, q: Search = "", limit: Limit = 20, offset: Offset = 0,
           category: s.Category | None = None, active: bool | None = None):
    return directory(request).dishes(actor, q, limit, offset, category, active)


@menu_router.post("/dishes", response_model=s.DishOut, status_code=201)
def create_dish(body: s.DishIn, request: Request, actor: Actor):
    return directory(request).create_dish(actor, body.name, body.category_code)


@menu_router.patch("/dishes/{dish_id}", response_model=s.DishOut)
def edit_dish(dish_id: ResourceId, body: s.DishEdit, request: Request, actor: Actor):
    return directory(request).change_dish(actor, dish_id, body.expected_name, body.expected_category, body.name, body.category_code)


@menu_router.delete("/dishes/{dish_id}", status_code=204)
def delete_dish(dish_id: ResourceId, body: s.DishDelete, request: Request, actor: Actor):
    directory(request).change_dish(actor, dish_id, body.expected_name, body.expected_category)


@menu_router.post("/menus", response_model=s.MenuOut, status_code=201)
def create_menu(body: s.MenuIn, request: Request, actor: Actor):
    return directory(request).create_menu(actor, body.label, body.dish_ids, assignments(body.assignments), body.include_default_rice, [change.model_dump() for change in body.dish_changes])


@menu_router.get("/menu-defaults", response_model=s.MenuDefaultsOut)
def menu_defaults(request: Request, actor: Actor):
    return directory(request).menu_defaults(actor)


@menu_router.put("/menus/{menu_id}/dates", response_model=s.ScheduleOut)
def schedule_menu(menu_id: ResourceId, body: s.ScheduleIn, request: Request, actor: Actor):
    return directory(request).assign_menu(actor, menu_id, assignments(body.assignments))


@menu_router.get("/menus/by-date/{service_date}", response_model=s.DatedMenuOut)
def dated_menu(service_date: date, request: Request, actor: Actor):
    return directory(request).menu_for_date(actor, service_date)


@menu_router.get("/menus/{menu_id}", response_model=s.MenuOut)
def recorded_menu(menu_id: ResourceId, request: Request, actor: Actor):
    return directory(request).menu_by_id(actor, menu_id)


@order_router.post("", response_model=OrderResult, status_code=201)
def create_order(body: s.OrderIn, request: Request, actor: Actor):
    command = CreateOrder(body.request_key, body.service_date, body.menu_id, selections(body.items),
                          allocations(body.allocations), body.employee_number, body.visitor_id)
    return OrderService(services(request)).create_pending(actor, command)


@order_router.get("", response_model=list[s.OrderSummary])
def orders(request: Request, actor: Actor, start: date | None = None, end: date | None = None,
           employee_number: Annotated[str | None, Query(min_length=1, max_length=200, pattern=r"^[^\x00]*$")] = None,
           visitor_id: Annotated[int | None, Query(gt=0, le=9223372036854775807)] = None,
           status: Literal["pending", "received"] | None = None, limit: Limit = 20, offset: Offset = 0,
           pending_first: bool = False):
    return directory(request).orders(actor, start=start, end=end, employee_number=employee_number, visitor_id=visitor_id,
        received=None if status is None else status == "received", limit=limit, offset=offset, pending_first=pending_first)


@order_router.get("/overview", response_model=s.OrderOverview)
def order_overview(day: date, request: Request, actor: Actor):
    return directory(request).order_overview(actor, day)


@order_router.get("/page", response_model=s.OrderPage)
def orders_page(request: Request, actor: Actor, start: date | None = None, end: date | None = None,
                employee_number: Annotated[str | None, Query(min_length=1, max_length=200, pattern=r"^[^\x00]*$")] = None,
                visitor_id: Annotated[int | None, Query(gt=0, le=9223372036854775807)] = None,
                status: Literal["pending", "received"] | None = None, limit: Limit = 20, offset: Offset = 0,
                revision: Annotated[str | None, Query(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")] = None):
    return directory(request).orders_page(actor, start=start, end=end, employee_number=employee_number, visitor_id=visitor_id,
        received=None if status is None else status == "received", limit=limit, offset=offset, revision=revision)


@order_router.get("/{order_id}", response_model=s.OrderDetail)
def order_detail(order_id: ResourceId, request: Request, actor: Actor):
    return directory(request).order_detail(actor, order_id)


@order_router.patch("/{order_id}", response_model=OrderResult)
def edit_order(order_id: ResourceId, body: s.EditIn, request: Request, actor: Actor):
    changes = EditPending(tuple(QuantityChange(i.line_id, i.quantity) for i in body.quantities),
                          tuple(body.remove_line_ids), selections(body.add_items),
                          None if body.allocations is None else allocations(body.allocations))
    return OrderService(services(request)).edit_pending(actor, order_id, body.expected_version, changes)


@order_router.post("/{order_id}/received", response_model=OrderResult)
def received(order_id: ResourceId, body: s.VersionIn, request: Request, actor: Actor):
    return OrderService(services(request)).mark_received(actor, order_id, body.expected_version)


@order_router.post("/{order_id}/reverse-received", response_model=OrderResult)
def reverse_received(order_id: ResourceId, body: s.ReversalIn, request: Request, actor: Admin):
    correction = Correction(body.reason_code, body.acknowledged, body.explanation)
    return OrderService(services(request)).reverse_received(actor, order_id, body.expected_version, correction)


def period(mode: Literal["daily", "weekly", "monthly", "custom"], day: date | None = None,
           year: Annotated[int | None, Query(ge=1, le=9999)] = None,
           month: Annotated[int | None, Query(ge=1, le=12)] = None,
           start: date | None = None, end: date | None = None):
    supplied = {key for key, value in {"day": day, "year": year, "month": month, "start": start, "end": end}.items()
                if value is not None}
    expected = {"daily": {"day"}, "weekly": {"day"}, "monthly": {"year", "month"}, "custom": {"start", "end"}}
    if supplied != expected[mode]:
        raise ReportInputError("Provide exactly the dates required by the selected period mode")
    if mode == "daily":
        return DateRange.daily(day)
    if mode == "weekly":
        return DateRange.weekly(day)
    if mode == "monthly":
        return DateRange.monthly(year, month)
    return DateRange(start, end)


Period = Annotated[DateRange, Depends(period)]


@report_router.get("/sales", response_model=SalesSummary)
def sales_report(request: Request, actor: Actor, dates: Period):
    return ReportingService(services(request)).sales_summary(actor, dates)


@report_router.get("/payments", response_model=PaymentSummary)
def payment_report(request: Request, actor: Actor, dates: Period):
    return ReportingService(services(request)).payment_summary(actor, dates)


@report_router.get("/salary-deduction", response_model=SalaryDeductionReport)
def sd_report(request: Request, actor: Actor, dates: Period):
    return ReportingService(services(request)).salary_deduction_report(actor, dates)


@report_router.get("/bundle", response_model=ExportReportBundle | ReportBundle)
def report_bundle(request: Request, actor: Actor, dates: Period, include_export_details: bool = False):
    return ReportingService(services(request)).report_bundle(actor, dates, include_export_details=include_export_details)
