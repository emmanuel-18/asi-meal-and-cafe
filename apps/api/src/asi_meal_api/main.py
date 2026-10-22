from fastapi import FastAPI

from contextlib import asynccontextmanager
import os

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from asi_meal_api.auth import AuthenticationFailed, CSRFRejected
from asi_meal_api.auth_http import AuthRuntime, router, runtime_from_environment
from asi_meal_api.business_http import directory_router, menu_router, order_router, report_router
from asi_meal_api.employee_imports import ImportHistoryError, ImportSourceError
from asi_meal_api.orders import Conflict, Forbidden, NotFound, OrderError
from asi_meal_api.reports import ReportInputError
from asi_meal_api.user_http import router as user_router


def create_app(auth: AuthRuntime | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application):
        engine = None
        try:
            if auth is None and os.environ.get("ASI_AUTH_ENABLED") == "true":
                try:
                    application.state.auth, engine = runtime_from_environment()
                except Exception:
                    raise RuntimeError("Invalid authentication configuration") from None
            yield
        finally:
            if engine is not None:
                engine.dispose()
                application.state.auth = None

    application = FastAPI(title="ASI Meal Management API", description="Internal API for ASI Meal Management.",
                          version="0.1.0", lifespan=lifespan)
    application.state.auth = auth

    @application.middleware("http")
    async def no_auth_cache(request, call_next):
        response = await call_next(request)
        if request.url.path.startswith(("/auth/", "/api/")):
            response.headers["Cache-Control"] = "no-store"
        return response

    @application.exception_handler(AuthenticationFailed)
    async def authentication_failed(request: Request, exc):
        return JSONResponse({"detail": "Authentication failed"}, status_code=401)

    @application.exception_handler(CSRFRejected)
    async def csrf_failed(request: Request, exc):
        return JSONResponse({"detail": "Request rejected"}, status_code=403)

    @application.exception_handler(Forbidden)
    async def forbidden(request: Request, exc):
        return JSONResponse({"detail": "Permission denied"}, status_code=403)

    @application.exception_handler(SQLAlchemyError)
    async def storage_failed(request: Request, exc):
        return JSONResponse({"detail": "Service unavailable"}, status_code=503)

    @application.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc):
        # Pydantic's default errors can echo employee values and submitted keys.
        return JSONResponse({"detail": "Invalid request"}, status_code=422)

    @application.exception_handler(OrderError)
    async def business_rejected(request: Request, exc):
        status = 404 if isinstance(exc, NotFound) else 409 if isinstance(exc, Conflict) else 422
        return JSONResponse({"detail": str(exc)}, status_code=status)

    @application.exception_handler(ReportInputError)
    @application.exception_handler(ImportSourceError)
    async def invalid_business_input(request: Request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @application.exception_handler(ImportHistoryError)
    async def import_history_unavailable(request: Request, exc):
        return JSONResponse({"detail": "Import outcome could not be confirmed", "import_id": exc.import_id}, status_code=503)

    @application.get("/health", tags=["Health"])
    def health_check() -> dict[str, str]:
        return {"status": "ok"}

    application.include_router(router)
    application.include_router(user_router)
    for business_router in (directory_router, menu_router, order_router, report_router):
        application.include_router(business_router)
    return application


app = create_app()
