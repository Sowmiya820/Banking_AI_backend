import asyncio
from sqlalchemy import select
from app.db.session import AsyncSessionLocal
from app.db.models.models import Role, DepositProduct


async def verify():
    async with AsyncSessionLocal() as session:
        # Check Roles
        roles = (await session.execute(select(Role))).scalars().all()
        print(f"✅ Found {len(roles)} roles in DB:")
        for r in roles:
            print(f"   - ID: {r.role_id} | Name: {r.role_name}")

        # Check Deposit Products
        products = (await session.execute(select(DepositProduct))).scalars().all()
        print(f"\n✅ Found {len(products)} deposit products in DB:")
        for p in products:
            print(f"   - {p.product_name} ({p.interest_rate}% interest)")


if __name__ == "__main__":
    asyncio.run(verify())