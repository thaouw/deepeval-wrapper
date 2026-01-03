from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer

from ..models.auth import Token, LoginRequest, User
from ..services.auth_service import AuthService
from ..config import settings
from ..auth import get_current_user

router = APIRouter(prefix="/auth", tags=["Authentication"])
security = HTTPBearer()
auth_service = AuthService()


@router.post("/login", response_model=Token)
async def login(login_request: LoginRequest):
    """Authenticate user and return access token."""
    user = auth_service.authenticate_user(login_request.username, login_request.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
    access_token = auth_service.create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    
    return Token(
        access_token=access_token,
        token_type="bearer",
        expires_in=settings.access_token_expire_minutes * 60
    )


@router.get("/me", response_model=User)
async def read_users_me(
    current_user: User = Depends(get_current_user)
):
    """Get current user information."""
    return current_user


@router.post("/validate-token")
async def validate_token(
    current_user: User = Depends(get_current_user)
):
    """Validate current token."""
    return {"valid": True, "user": current_user}
