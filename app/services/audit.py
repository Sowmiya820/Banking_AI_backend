from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models.models import AuditLog


async def log_audit_event(
    db: AsyncSession,
    action: str,
    endpoint: str,
    user_id: Optional[int] = None,
    details: Optional[str] = None
):
    """Writes an entry to the audit_logs table with a default timestamp."""
    log_entry = AuditLog(
        user_id=user_id,
        action=action,
        endpoint=endpoint,
        details=details,
        timestamp=datetime.now(timezone.utc)  # Fixed: provides current timestamp
    )
    db.add(log_entry)
    await db.commit()