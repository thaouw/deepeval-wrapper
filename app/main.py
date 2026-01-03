import time
from contextlib import asynccontextmanager
from typing import Optional
from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import logging

from .config import settings
from .models.auth import User
from .auth import get_optional_user
from .api import (
    evaluation_router,
    auth_router,
    metrics_router,
    jobs_router,
    health_router,
)

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format=settings.log_format
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    logger.info(f"Starting {settings.app_name} v{settings.version}")
    
    # Initialize services
    try:
        from .services.deepeval_service import DeepEvalService
        deepeval_service = DeepEvalService()
        health_data = deepeval_service.health_check()
        
        if not health_data["deepeval_available"]:
            logger.warning("DeepEval library not available!")
        else:
            logger.info(f"DeepEval available - {health_data['supported_metrics']} metrics supported")
        
        if health_data["openai_configured"]:
            logger.info("OpenAI API key configured")
        else:
            logger.warning("OpenAI API key not configured")
            
    except Exception as e:
        logger.error(f"Failed to initialize services: {e}")
    
    yield
    
    # Shutdown
    logger.info("Shutting down application")


# Create FastAPI app
app = FastAPI(
    title=settings.app_name,
    description="REST API wrapper for DeepEval Python library",
    version=settings.version,
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=settings.cors_allow_methods,
    allow_headers=settings.cors_allow_headers,
)


# Request timing middleware
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(process_time)
    return response


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error",
            "error_type": type(exc).__name__,
            "path": request.url.path
        }
    )


# Include routers
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(evaluation_router)
app.include_router(metrics_router)
app.include_router(jobs_router)


# Root endpoint
@app.get("/", tags=["Root"])
async def root(request: Request, current_user: Optional[User] = Depends(get_optional_user)):
    """Root endpoint with basic information."""
    
    if current_user is None:
        return {
            "message": "Authentication Required",
            "detail": "You need to be authenticated to access this API. Please provide either a Bearer token or X-API-Key header.",
            "version": settings.version,
            "docs": "/docs",
            "authentication": {
                "methods": ["JWT Bearer Token", "API Key (X-API-Key header)"],
                "endpoints": {
                    "login": "/auth/login",
                    "validate": "/auth/validate-token",
                    "user_info": "/auth/me"
                }
            }
        }
    
    return {
        "message": f"Welcome to {settings.app_name}",
        "version": settings.version,
        "docs": "/docs",
        "health": "/health",
        "authenticated": True,
        "user": current_user.username,
        "endpoints": {
            "authentication": "/auth",
            "evaluation": "/evaluate",
            "metrics": "/metrics", 
            "jobs": "/jobs",
            "health": "/health"
        }
    }


# API Info endpoint
@app.get("/info", tags=["Root"])
async def api_info():
    """Get API information."""
    return {
        "name": settings.app_name,
        "version": settings.version,
        "description": "REST API wrapper for DeepEval Python library",
        "supported_features": [
            "30+ evaluation metrics",
            "Single and batch evaluation",
            "Asynchronous job processing",
            "Multiple test case types (LLM, Conversational, Multimodal, Arena)",
            "JWT and API key authentication",
            "Dataset file upload and processing",
            "Comprehensive error handling"
        ],
        "authentication": {
            "methods": ["JWT Bearer Token", "API Key (X-API-Key header)"],
            "endpoints": {
                "login": "/auth/login",
                "validate": "/auth/validate-token",
                "user_info": "/auth/me"
            }
        },
        "evaluation": {
            "sync_endpoints": ["/evaluate", "/evaluate/bulk"],
            "async_endpoints": ["/evaluate/async", "/evaluate/async/bulk", "/evaluate/dataset"],
            "supported_formats": ["JSON", "CSV", "JSONL"]
        },
        "limits": {
            "max_file_size_mb": settings.max_file_size // 1024 // 1024,
            "default_max_concurrent": settings.default_max_concurrent,
            "default_timeout_seconds": settings.default_timeout
        }
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level=settings.log_level.lower()
    )
