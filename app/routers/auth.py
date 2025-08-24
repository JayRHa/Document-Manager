"""
Authentication Router
Handles login, logout, user management, and authentication endpoints
"""

from datetime import timedelta, datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Request, Response
from sqlalchemy.orm import Session
from pydantic import BaseModel

from ..database import get_db
from ..models import User
from ..services.auth_service import (
    AuthService, get_current_user_from_session, get_current_user_flexible,
    require_admin_flexible, ACCESS_TOKEN_EXPIRE_MINUTES
)
from ..services.doctype_manager import ensure_default_document_types
from ..config import get_settings

router = APIRouter()

@router.get("/csrf-token")
async def get_csrf_token(request: Request):
    """Get CSRF token from cookie"""
    csrf_token = request.cookies.get("csrf_token")
    if csrf_token:
        # Extract the actual token from signed cookie
        token = csrf_token.split('.')[0] if '.' in csrf_token else csrf_token
        return {"csrf_token": token}
    return {"csrf_token": None}

# Pydantic models
class Token(BaseModel):
    access_token: str
    token_type: str
    must_change_password: Optional[bool] = False

class UserCreate(BaseModel):
    username: str
    email: str
    full_name: Optional[str] = None
    password: str
    is_admin: bool = False

class UserUpdate(BaseModel):
    username: Optional[str] = None
    email: Optional[str] = None
    full_name: Optional[str] = None
    is_active: Optional[bool] = None
    is_admin: Optional[bool] = None
    password: Optional[str] = None

class PasswordChange(BaseModel):
    current_password: str
    new_password: str

class UserResponse(BaseModel):
    id: str
    username: str
    email: str
    full_name: Optional[str]
    is_active: bool
    is_admin: bool
    last_login: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True

class LoginRequest(BaseModel):
    username: str
    password: str

@router.post("/login", response_model=Token)
async def login(
    request: Request,
    response: Response,
    login_data: LoginRequest,
    db: Session = Depends(get_db)
):
    """Login endpoint"""
    auth_service = AuthService(db)
    
    user = auth_service.authenticate_user(login_data.username, login_data.password)
    if not user:
        auth_service.log_audit_event(
            user_id=None,
            action="login_failed",
            details={"username": login_data.username},
            ip_address=request.client.host,
            user_agent=request.headers.get("user-agent")
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Create JWT token
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = auth_service.create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    
    # Create session
    session_token = auth_service.create_session(
        user,
        ip_address=request.client.host,
        user_agent=request.headers.get("user-agent")
    )
    
    # Get settings to check production mode
    settings = get_settings(db)
    
    # Set session cookie
    response.set_cookie(
        key="session_token",
        value=session_token,
        max_age=24 * 60 * 60,  # 24 hours
        httponly=True,
        secure=settings.production_mode,  # Secure cookies in production
        samesite="lax"
    )
    
    # Log successful login
    auth_service.log_audit_event(
        user_id=user.id,
        action="login_success",
        ip_address=request.client.host,
        user_agent=request.headers.get("user-agent")
    )
    
    return {
        "access_token": access_token, 
        "token_type": "bearer",
        "must_change_password": user.must_change_password
    }

@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_session)
):
    """Logout endpoint"""
    auth_service = AuthService(db)
    
    # Get session token from cookie
    session_token = request.cookies.get("session_token")
    if session_token:
        auth_service.invalidate_session(session_token)
    
    # Clear session cookie
    response.delete_cookie(key="session_token")
    
    # Log logout
    if current_user:
        auth_service.log_audit_event(
            user_id=current_user.id,
            action="logout",
            ip_address=request.client.host,
            user_agent=request.headers.get("user-agent")
        )
    
    return {"message": "Successfully logged out"}

@router.get("/me", response_model=UserResponse)
async def get_current_user_info(current_user: User = Depends(get_current_user_flexible)):
    """Get current user information"""
    return current_user

@router.post("/change-password")
async def change_password(
    password_data: PasswordChange,
    current_user: User = Depends(get_current_user_flexible),
    db: Session = Depends(get_db)
):
    """Change user password"""
    auth_service = AuthService(db)
    
    # Verify current password
    if not current_user.verify_password(password_data.current_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect"
        )
    
    # Set new password
    current_user.set_password(password_data.new_password)
    current_user.must_change_password = False  # Clear the flag
    db.commit()
    
    # Log password change
    auth_service.log_audit_event(
        user_id=current_user.id,
        action="password_changed"
    )
    
    return {"message": "Password changed successfully"}

@router.get("/check-session")
async def check_session(
    current_user: User = Depends(get_current_user_from_session),
    db: Session = Depends(get_db)
):
    """Check if session is valid"""
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session"
        )
    
    return {
        "valid": True,
        "user": {
            "id": current_user.id,
            "username": current_user.username,
            "email": current_user.email,
            "full_name": current_user.full_name,
            "is_admin": current_user.is_admin
        }
    }

# Admin endpoints
@router.post("/users", response_model=UserResponse)
async def create_user(
    user_data: UserCreate,
    current_user: User = Depends(require_admin_flexible),
    db: Session = Depends(get_db)
):
    """Create new user (admin only)"""
    auth_service = AuthService(db)
    
    # Check if user already exists
    existing_user = db.query(User).filter(
        (User.username == user_data.username) | (User.email == user_data.email)
    ).first()
    
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User with this username or email already exists"
        )
    
    # Create user
    user = User(
        username=user_data.username,
        email=user_data.email,
        full_name=user_data.full_name,
        is_admin=user_data.is_admin,
        is_active=True
    )
    user.set_password(user_data.password)
    
    db.add(user)
    db.commit()
    db.refresh(user)
    
    # Log user creation
    auth_service.log_audit_event(
        user_id=current_user.id,
        action="user_created",
        resource_type="user",
        resource_id=user.id,
        details={"username": user.username, "email": user.email}
    )
    
    return user

@router.get("/users", response_model=list[UserResponse])
async def list_users(
    current_user: User = Depends(require_admin_flexible),
    db: Session = Depends(get_db)
):
    """List all users (admin only)"""
    users = db.query(User).all()
    return users

@router.get("/users/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: str,
    current_user: User = Depends(require_admin_flexible),
    db: Session = Depends(get_db)
):
    """Get user by ID (admin only)"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    return user

@router.put("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: str,
    user_data: UserUpdate,
    current_user: User = Depends(require_admin_flexible),
    db: Session = Depends(get_db)
):
    """Update user (admin only)"""
    auth_service = AuthService(db)
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Update fields
    update_data = user_data.dict(exclude_unset=True)
    
    # Handle password separately
    if 'password' in update_data and update_data['password']:
        user.set_password(update_data['password'])
        del update_data['password']
    
    # Update other fields
    for field, value in update_data.items():
        setattr(user, field, value)
    
    db.commit()
    db.refresh(user)
    
    # Log user update
    auth_service.log_audit_event(
        user_id=current_user.id,
        action="user_updated",
        resource_type="user",
        resource_id=user.id,
        details=update_data
    )
    
    return user

@router.delete("/users/{user_id}")
async def delete_user(
    user_id: str,
    current_user: User = Depends(require_admin_flexible),
    db: Session = Depends(get_db)
):
    """Delete user (admin only)"""
    auth_service = AuthService(db)
    
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account"
        )
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Log user deletion before deleting
    auth_service.log_audit_event(
        user_id=current_user.id,
        action="user_deleted",
        resource_type="user",
        resource_id=user.id,
        details={"username": user.username, "email": user.email}
    )
    
    db.delete(user)
    db.commit()
    
    return {"message": "User deleted successfully"}

@router.get("/setup/check")
async def check_setup_status(db: Session = Depends(get_db)):
    """Check if initial setup is complete"""
    user_count = db.query(User).count()
    return {
        "setup_complete": user_count > 0,
        "user_count": user_count
    }

@router.post("/setup/initial-user")
async def create_initial_user(
    request: Request,
    user_data: UserCreate,
    db: Session = Depends(get_db)
):
    """Create initial admin user during setup"""
    # Check if any users exist
    user_count = db.query(User).count()
    if user_count > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Initial setup already completed"
        )
    
    auth_service = AuthService(db)
    
    # Create default roles
    auth_service.create_default_roles()
    
    # Create default document types
    ensure_default_document_types(db)
    
    # Create admin user
    try:
        user = auth_service.create_admin_user(
            username=user_data.username,
            email=user_data.email,
            password=user_data.password,
            full_name=user_data.full_name
        )
        
        # Log initial setup
        auth_service.log_audit_event(
            user_id=user.id,
            action="initial_setup",
            details={"username": user.username, "email": user.email},
            ip_address=request.client.host,
            user_agent=request.headers.get("user-agent")
        )
        
        return {"message": "Initial admin user created successfully", "user_id": user.id}
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )