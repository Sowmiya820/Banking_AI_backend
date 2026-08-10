# app/api/v1/endpoints/dashboard.py

from fastapi import APIRouter, Depends
from app.db.models.models import User
from app.core.dependencies import require_roles

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


# Option A: Route where you need user data inside the function
@router.get("/my-summary")
async def get_my_dashboard(
    current_user: User = Depends(require_roles(["BANKER", "ANALYST"]))
):
    return {
        "message": f"Welcome back, {current_user.username}",
        "role": current_user.role.role_name
    }


# Option B: Route where you only need authorization check (no user object in code)
@router.get("/system-health", dependencies=[Depends(require_roles(["ADMIN"]))])
async def get_system_health():
    return {"status": "healthy", "database": "connected"}