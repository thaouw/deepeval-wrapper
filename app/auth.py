from typing import Optional
from fastapi import Depends, HTTPException, status, Header, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from .models.auth import User
from .services.auth_service import AuthService

# Initialize services
auth_service = AuthService()
security = HTTPBearer(auto_error=False)


async def get_current_user_from_token(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> Optional[User]:
    """Get current user from JWT token."""
    if not credentials:
        return None
    
    try:
        token_data = auth_service.verify_token(credentials.credentials)
        user = auth_service.get_user_by_token(token_data)
        return user
    except HTTPException:
        return None


async def get_current_user_from_api_key(request: Request) -> Optional[User]:
    """Get current user from API key."""
    # Try to get API key from header (case-insensitive)
    api_key = None
    for header_name, header_value in request.headers.items():
        if header_name.lower() == "x-api-key":
            api_key = header_value
            break
    
    if not api_key:
        return None
    
    if auth_service.validate_api_key(api_key):
        return auth_service.get_api_user()
    
    return None


async def get_current_user(
    request: Request,
    user_from_token: Optional[User] = Depends(get_current_user_from_token),
) -> User:
    """Get current user from either JWT token or API key."""
    # Try API key authentication
    user_from_api_key = await get_current_user_from_api_key(request)
    
    # Use token user or API key user
    user = user_from_token or user_from_api_key
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Provide either Bearer token or X-API-Key header.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return user


async def get_current_admin_user(current_user: User = Depends(get_current_user)) -> User:
    """Get current user with admin privileges."""
    if "admin" not in current_user.scopes:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required"
        )
    return current_user


# Optional authentication (doesn't raise error if not authenticated)
async def get_optional_user(
    request: Request,
    user_from_token: Optional[User] = Depends(get_current_user_from_token),
) -> Optional[User]:
    """Get current user if authenticated, otherwise None."""
    user_from_api_key = await get_current_user_from_api_key(request)
    return user_from_token or user_from_api_key
