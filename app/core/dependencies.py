from typing import List, Optional
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.db.session import get_db
from app.db.models.models import User, ModulePermission
from app.schemas.token import TokenPayload

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/login",
    auto_error=False
)


async def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db)
) -> User:
    """Validate JWT token and return active user."""
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token missing",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        username: str = payload.get("sub")
        if not username:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        token_data = TokenPayload(sub=username, role=payload.get("role"))

    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Normalize token subject (email or username)
    identifier = token_data.sub.strip().lower()

    # 🔑 FIX: Check both User.email AND User.username case-insensitively
    stmt = (
        select(User)
        .options(selectinload(User.role))
        .where(
            (func.lower(User.email) == identifier) | 
            (func.lower(User.username) == identifier)
        )
    )
    result = await db.execute(stmt)
    user = result.scalars().first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account not found"
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive"
        )

    return user


async def get_current_user_optional(
    token: Optional[str] = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db)
) -> Optional[User]:
    """Return User if Bearer token present, else None for optional logging."""
    if not token:
        return None
    try:
        return await get_current_user(token=token, db=db)
    except HTTPException:
        return None


def require_roles(allowed_roles: List[str]):
    """Role-Based Access Control (RBAC) dependency factory."""
    async def role_checker(current_user: User = Depends(get_current_user)) -> User:
        # Safely extract the role string across different object types
        user_role = ""
        if isinstance(current_user.role, str):
            user_role = current_user.role
        elif hasattr(current_user.role, "role_name"):
            user_role = getattr(current_user.role, "role_name", "") or ""
        elif hasattr(current_user.role, "name"):
            user_role = getattr(current_user.role, "name", "") or ""

        # Normalize both stored role and allowed roles for reliable matching
        user_role_normalized = user_role.upper().replace(" ", "_")
        allowed_normalized = [r.upper().replace(" ", "_") for r in allowed_roles]

        if not user_role or user_role_normalized not in allowed_normalized:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required role(s): {allowed_roles}. Your role: {user_role or 'None'}"
            )
        return current_user

    return role_checker


def require_module_access(module_code: str):
    """
    Module Access Security Dependency.
    Checks if the current user's role has access granted to module_code (e.g. 'A1', 'A2', 'A3', 'A4').
    """
    async def module_checker(
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db)
    ) -> User:
        # Extract role name
        user_role = ""
        if isinstance(current_user.role, str):
            user_role = current_user.role
        elif hasattr(current_user.role, "role_name"):
            user_role = getattr(current_user.role, "role_name", "") or ""
        elif hasattr(current_user.role, "name"):
            user_role = getattr(current_user.role, "name", "") or ""

        user_role_normalized = user_role.upper().replace(" ", "_")

        # ADMINs bypass module level restriction
        if user_role_normalized == "ADMIN":
            return current_user

        # Query module permission rule
        stmt = select(ModulePermission).where(
            ModulePermission.role_name == user_role_normalized,
            ModulePermission.module_code == module_code.upper()
        )
        res = await db.execute(stmt)
        perm = res.scalars().first()

        # If a specific rule exists and is explicitly disabled, block access
        if perm and not perm.is_allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access to Module {module_code.upper()} is restricted for role '{user_role_normalized}'."
            )

        return current_user

    return module_checker