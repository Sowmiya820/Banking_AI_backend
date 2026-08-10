import asyncio
from app.db.session import engine, Base
from app.db.models import models  # Register models


async def init_db():
    async with engine.begin() as conn:
        # Create missing tables (policy_documents, policy_chunks, deposit_products)
        await conn.run_sync(Base.metadata.create_all)
        print("✅ Database schema synchronized successfully!")


if __name__ == "__main__":
    asyncio.run(init_db())