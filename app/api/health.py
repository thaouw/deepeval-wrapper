from datetime import datetime
from fastapi import APIRouter, Depends, Request
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


@router.get("/debug-auth")
async def debug_auth(request: Request):
    """Debug endpoint to check authentication headers (no auth required)."""
    from ..auth import get_current_user_from_api_key
    from ..config import settings
    
    # Get all headers
    all_headers = dict(request.headers)
    
    # Try to get API key
    api_key_header = None
    for header_name, header_value in request.headers.items():
        if header_name.lower() == "x-api-key":
            api_key_header = header_value
            break
    
    # Check validation
    api_key_valid = False
    if api_key_header:
        from ..services.auth_service import AuthService
        auth_service = AuthService()
        api_key_valid = auth_service.validate_api_key(api_key_header)
    
    return {
        "x_api_key_header_found": api_key_header is not None,
        "x_api_key_value": api_key_header[:10] + "..." if api_key_header and len(api_key_header) > 10 else api_key_header,
        "x_api_key_length": len(api_key_header) if api_key_header else 0,
        "api_key_valid": api_key_valid,
        "configured_api_keys_count": len(settings.api_keys_list),
        "configured_api_keys_preview": [key[:10] + "..." if len(key) > 10 else key for key in settings.api_keys_list[:3]],
        "all_headers": {k: v[:50] + "..." if len(v) > 50 else v for k, v in all_headers.items()},
    }
