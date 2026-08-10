from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.db.session import get_db
from app.db.models.models import Customer, User
from app.services.audit import log_audit_event
from app.core.dependencies import require_roles

router = APIRouter()


@router.get("/customers/{customer_id}")
async def get_customer_360(
    customer_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(["LOAN_OFFICER", "RELATIONSHIP_MANAGER", "ADMIN"]))
):
    stmt = (
        select(Customer)
        .options(
            selectinload(Customer.accounts),
            selectinload(Customer.loans),
            selectinload(Customer.loan_applications),
            selectinload(Customer.limits)
        )
        .where(Customer.customer_id == customer_id)
    )
    
    result = await db.execute(stmt)
    customer = result.scalar_one_or_none()

    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Customer ID {customer_id} not found."
        )

    await log_audit_event(
        db=db,
        user_id=current_user.user_id,
        action="VIEW_CUSTOMER_360",
        endpoint=f"/api/v1/banking/customers/{customer_id}",
        details=f"Retrieved profile and records for Customer ID {customer_id}"
    )

    return customer