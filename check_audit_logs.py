import asyncio
from sqlalchemy import select
from app.db.session import AsyncSessionLocal
from app.db.models.models import AuditLog


async def check():
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(AuditLog))
        logs = result.scalars().all()
        print(f"✅ Found {len(logs)} audit log entries in DB:")
        for log in logs:
            print(f"   - [ID: {log.log_id}] Action: {log.action} | Resource: {log.resource} | Time: {log.timestamp}")


if __name__ == "__main__":
    asyncio.run(check())