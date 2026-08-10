import asyncio
from sqlalchemy import select
from app.db.session import AsyncSessionLocal
from app.db.models.models import Role, DepositProduct


async def seed():
    async with AsyncSessionLocal() as session:
        # 1. Seed Roles safely
        desired_roles = ["ADMIN", "LOAN_OFFICER", "COMPLIANCE_OFFICER", "CUSTOMER"]
        
        # Get all existing role names in one query
        existing_roles_res = await session.execute(select(Role.role_name))
        existing_role_names = set(existing_roles_res.scalars().all())

        added_roles = False
        for role_name in desired_roles:
            if role_name not in existing_role_names:
                session.add(Role(role_name=role_name, description=f"{role_name} access level"))
                added_roles = True

        if added_roles:
            await session.commit()
            print("✅ New roles seeded!")
        else:
            print("ℹ️ Roles already exist, skipping.")

        # 2. Seed Deposit Products safely
        products = [
            {
                "product_name": "Flexi Savings Account",
                "category": "SAVINGS",
                "interest_rate": 4.5,
                "min_amount": 1000.0,
                "description": "High yield flexible savings with instant liquidity."
            },
            {
                "product_name": "Fixed Deposit Super 1Y",
                "category": "TERM_DEPOSIT",
                "interest_rate": 7.25,
                "min_amount": 10000.0,
                "min_tenure_months": 12,
                "max_tenure_months": 12,
                "description": "1-Year Fixed Deposit with maximum returns.",
                "penalty_terms": "1% interest penalty on premature withdrawal."
            }
        ]

        existing_prods_res = await session.execute(select(DepositProduct.product_name))
        existing_prod_names = set(existing_prods_res.scalars().all())

        added_prods = False
        for prod_data in products:
            if prod_data["product_name"] not in existing_prod_names:
                session.add(DepositProduct(**prod_data))
                added_prods = True

        if added_prods:
            await session.commit()
            print("✅ Deposit products seeded!")
        else:
            print("ℹ️ Deposit products already exist, skipping.")


if __name__ == "__main__":
    asyncio.run(seed())