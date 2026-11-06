import os
from pathlib import Path
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.app.api.v1.router import api_v1_router
from backend.app.core.config import settings
from backend.app.core.logging import logger, setup_logging
from backend.app.schemas.error import ErrorResponse
from backend.app.schemas.health import HealthResponse


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application startup and shutdown lifespan handler."""
    setup_logging()
    logger.info("Starting %s v%s in %s mode", settings.APP_NAME, settings.APP_VERSION, settings.APP_ENV)
    yield
    logger.info("Shutting down %s", settings.APP_NAME)


def create_app() -> FastAPI:
    """Application factory for the FastAPI backend."""
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        docs_url="/docs" if (settings.DEBUG or settings.APP_ENV == "development") else None,
        redoc_url="/redoc" if (settings.DEBUG or settings.APP_ENV == "development") else None,
        openapi_url="/openapi.json" if (settings.DEBUG or settings.APP_ENV == "development") else None,
        lifespan=lifespan,
    )

    # Global Exception Handlers for safe, non-leaking error responses
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        logger.warning("HTTP %d error on %s: %s", exc.status_code, request.url.path, exc.detail)
        payload = ErrorResponse(
            error_code=f"HTTP_{exc.status_code}",
            message=str(exc.detail),
        )
        return JSONResponse(status_code=exc.status_code, content=payload.model_dump(mode="json"))

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        logger.warning("Validation error on %s: %s", request.url.path, exc.errors())
        # Sanitize validation errors to exclude raw input values
        sanitized_details = [
            {
                "field": " -> ".join(str(loc) for loc in err.get("loc", [])),
                "issue": err.get("msg", "Invalid value"),
                "type": err.get("type", "value_error"),
            }
            for err in exc.errors()
        ]
        payload = ErrorResponse(
            error_code="VALIDATION_ERROR",
            message="Request input validation failed.",
            details=sanitized_details,
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=payload.model_dump(mode="json"),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        # Log error securely without printing user payload
        logger.error("Unhandled server exception on %s: %s", request.url.path, exc.__class__.__name__, exc_info=True)
        payload = ErrorResponse(
            error_code="INTERNAL_SERVER_ERROR",
            message="An unexpected internal error occurred. Please contact the administrator.",
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=payload.model_dump(mode="json"),
        )

    # Include API v1 router
    # Prevent stale browser caching of frontend static assets
    @app.middleware("http")
    async def add_no_cache_headers(request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path.startswith("/static/") or path in ("/", "/ui"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

    app.include_router(api_v1_router, prefix=settings.API_V1_PREFIX)

    # Convenience root-level health endpoint matching API v1 health
    @app.get(
        "/health",
        response_model=HealthResponse,
        include_in_schema=False,
    )
    def root_health() -> HealthResponse:
        return HealthResponse(
            status="healthy",
            app_name=settings.APP_NAME,
            version=settings.APP_VERSION,
            environment=settings.APP_ENV,
        )

    # Static files and Web UI
    frontend_dir = (Path(__file__).resolve().parent.parent.parent / "frontend").resolve()
    if frontend_dir.exists():
        app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")

        @app.get("/ui", include_in_schema=False)
        def ui_page() -> FileResponse:
            return FileResponse(str(frontend_dir / "index.html"), media_type="text/html")

    @app.get("/", include_in_schema=False)
    def root(request: Request):
        accept = request.headers.get("accept", "")
        if frontend_dir.exists() and "text/html" in accept:
            return FileResponse(str(frontend_dir / "index.html"), media_type="text/html")
        return {
            "app": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "status": "online",
        }

    return app


app = create_app()
