import asyncio
from sqlalchemy import text
from app.db.session import engine

async def sync():
    async with engine.begin() as conn:
        # Update user_id constraint
        await conn.execute(text("ALTER TABLE audit_logs ALTER COLUMN user_id DROP NOT NULL;"))
        # Update timestamp default constraint
        await conn.execute(text("ALTER TABLE audit_logs ALTER COLUMN timestamp SET DEFAULT CURRENT_TIMESTAMP;"))
    print("✅ PostgreSQL schema synced with SQLAlchemy models!")

if __name__ == "__main__":
    asyncio.run(sync())