import logging
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.db.session import get_db
from app.db.models.models import User, Role
from app.core.security import verify_password, get_password_hash, create_access_token
from app.schemas.token import Token
from app.schemas.user import UserCreate, UserResponse
from app.core.dependencies import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register_user(
    user_in: UserCreate,
    db: AsyncSession = Depends(get_db)
):
    clean_email = user_in.email.strip().lower()
    clean_username = user_in.username.strip()

    # Case-insensitive check if username or email already exists
    stmt = select(User).where(
        (func.lower(User.username) == clean_username.lower()) | 
        (func.lower(User.email) == clean_email)
    )
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
        username=clean_username,
        email=clean_email,
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
        role_name=created_user.role.role_name if created_user.role else role_name,
        is_active=created_user.is_active
    )


@router.post("/login", response_model=Token)
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db)
):
    # Clean and normalize identifier & password input strings
    identifier = form_data.username.strip().lower()
    raw_password = form_data.password.strip()

    # Query database for case-insensitive match on email or username
    result = await db.execute(
        select(User)
        .options(selectinload(User.role))
        .where(
            (func.lower(User.email) == identifier) | 
            (func.lower(User.username) == identifier)
        )
    )
    user = result.scalars().first()

    # 🔍 DIAGNOSTIC LOGGING TO TERMINAL
    print("\n" + "=" * 50)
    print("🔐 [AUTH DIAGNOSTIC CHECK]")
    print(f" ➔ Submitted Identifier : '{identifier}'")
    print(f" ➔ User Found in DB?    : {user is not None}")

    if not user:
        print(" ❌ REASON FOR 401      : User record not found in database.")
        print("=" * 50 + "\n")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email/username or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Validate password hash
    is_password_valid = verify_password(raw_password, user.hashed_password)
    print(f" ➔ DB User Email        : '{user.email}'")
    print(f" ➔ DB Password Hash     : {user.hashed_password[:20]}...")
    print(f" ➔ Password Valid?      : {is_password_valid}")
    print(f" ➔ Is Active?           : {user.is_active}")

    if not is_password_valid:
        print(" ❌ REASON FOR 401      : Password comparison failed (Hash mismatch).")
        print("=" * 50 + "\n")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email/username or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        print(" ❌ REASON FOR 401      : Account is deactivated (is_active=False).")
        print("=" * 50 + "\n")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="User account is deactivated. Please contact an administrator."
        )

    print(" ✅ LOGIN SUCCESSFUL!")
    print("=" * 50 + "\n")

    role_name = user.role.role_name if user.role else "USER"

    access_token = create_access_token(
        subject=user.email,
        role=role_name
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "role": role_name,
        "username": user.username or user.email
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