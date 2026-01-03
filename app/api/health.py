from datetime import datetime
from fastapi import APIRouter, Depends
from typing import Optional

from ..models.health import HealthResponse
from ..models.auth import User
from ..services.deepeval_service import DeepEvalService
from ..config import settings
from ..auth import get_current_user

router = APIRouter(prefix="/health", tags=["Health"])
deepeval_service = DeepEvalService()


@router.get("/", response_model=HealthResponse)
async def health_check():
    """Health check endpoint - no authentication required."""
    try:
        health_data = deepeval_service.health_check()
        
        # Check Redis availability (if configured)
        redis_available = None
        if settings.use_redis and settings.redis_url:
            try:
                import redis
                r = redis.from_url(settings.redis_url)
                r.ping()
                redis_available = True
            except Exception:
                redis_available = False
        elif not settings.use_redis:
            redis_available = None  # Not using Redis, so not applicable
        
        status = "healthy"
        errors = []
        
        if not health_data["deepeval_available"]:
            status = "unhealthy"
            errors.append("DeepEval library not available")
        
        if redis_available is False:
            status = "degraded" if status == "healthy" else status
            errors.append("Redis not available")
        
        return HealthResponse(
            status=status,
            version=settings.version,
            timestamp=datetime.now().isoformat(),
            deepeval_available=health_data["deepeval_available"],
            redis_available=redis_available,
            openai_configured=health_data["openai_configured"],
            anthropic_configured=health_data.get("anthropic_configured"),
            google_configured=health_data.get("google_configured"),
            system_info={
                "supported_metrics": health_data["supported_metrics"],
                "deepeval_version": health_data.get("deepeval_version"),
            },
            errors=errors if errors else None,
        )
    
    except Exception as e:
        return HealthResponse(
            status="unhealthy",
            version=settings.version,
            timestamp=datetime.now().isoformat(),
            deepeval_available=False,
            openai_configured=False,
            errors=[f"Health check failed: {str(e)}"]
        )


@router.get("/detailed")
async def detailed_health_check(
    current_user: User = Depends(get_current_user)
):
    """Detailed health check - requires authentication."""
    health_data = deepeval_service.health_check()
    
    return {
        "status": "healthy" if health_data["deepeval_available"] else "unhealthy",
        "timestamp": datetime.now().isoformat(),
        "user": current_user.username,
        "services": {
            "deepeval": {
                "available": health_data["deepeval_available"],
                "version": health_data.get("deepeval_version"),
                "supported_metrics": health_data["supported_metrics"],
            },
            "llm_providers": {
                "openai": health_data["openai_configured"],
                "anthropic": health_data.get("anthropic_configured", False),
                "google": health_data.get("google_configured", False),
            },
        },
        "configuration": {
            "max_concurrent": settings.default_max_concurrent,
            "timeout": settings.default_timeout,
            "api_keys_configured": len(settings.api_keys_list),
        }
    }
