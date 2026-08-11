from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.db.session import get_db
from app.db.models.models import User, Role
from app.core.security import verify_password, get_password_hash, create_access_token
from app.schemas.token import Token
from app.schemas.user import UserCreate, UserResponse
from app.core.dependencies import get_current_user

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register_user(
    user_in: UserCreate,
    db: AsyncSession = Depends(get_db)
):
    # Check if username or email exists
    stmt = select(User).where((User.username == user_in.username) | (User.email == user_in.email))
    existing_user = (await db.execute(stmt)).scalar_one_or_none()

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username or email already registered."
        )

    # Normalize role name (e.g., "Loan Officer" -> "LOAN_OFFICER")
    role_name = user_in.role_name.strip().upper().replace(" ", "_")
    role_stmt = select(Role).where(Role.role_name == role_name)
    role = (await db.execute(role_stmt)).scalar_one_or_none()

    if not role:
        role = Role(role_name=role_name, description=f"System Role for {role_name}")
        db.add(role)
        await db.flush()

    new_user = User(
        username=user_in.username,
        email=user_in.email,
        hashed_password=get_password_hash(user_in.password),
        role_id=role.role_id,
        is_active=True
    )
    db.add(new_user)
    await db.commit()
    
    # Reload user with role relation loaded
    res = await db.execute(
        select(User).options(selectinload(User.role)).where(User.user_id == new_user.user_id)
    )
    created_user = res.scalar_one()

    return UserResponse(
        user_id=created_user.user_id,
        username=created_user.username,
        email=created_user.email,
        role_name=created_user.role.role_name,
        is_active=created_user.is_active
    )


@router.post("/login", response_model=Token)
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(User).options(selectinload(User.role)).where(User.username == form_data.username)
    )
    user = result.scalars().first()

    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Inactive user account")

    access_token = create_access_token(
        subject=user.username,
        role=user.role.role_name
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "role": user.role.role_name,
        "username": user.username
    }


@router.get("/me", response_model=UserResponse)
async def read_users_me(current_user: User = Depends(get_current_user)):
    return UserResponse(
        user_id=current_user.user_id,
        username=current_user.username,
        email=current_user.email,
        role_name=current_user.role.role_name if current_user.role else "USER",
        is_active=current_user.is_active
    )