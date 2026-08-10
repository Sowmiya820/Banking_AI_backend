import asyncio
from sqlalchemy import text
from app.db.session import engine


async def fix():
    async with engine.begin() as conn:
        await conn.execute(text("ALTER TABLE audit_logs ALTER COLUMN user_id DROP NOT NULL;"))
    print("✅ audit_logs.user_id is now nullable!")


if __name__ == "__main__":
    asyncio.run(fix())