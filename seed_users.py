import asyncio
from sqlalchemy import text, select
from app.db.session import AsyncSessionLocal
from app.db.models.models import User, Role
from app.core.security import get_password_hash

# 📋 Fresh test accounts with clear roles and passwords
DEMO_USERS = [
    {
        "username": "loan_officer_1",
        "email": "loan_officer_1@bank.com",
        "password": "1234",
        "role_name": "LOAN_OFFICER",
    },
    {
        "username": "rm1",
        "email": "rm1@gmail.com",
        "password": "1234",
        "role_name": "RELATIONSHIP_MANAGER",
    },
    {
        "username": "rm1_bank",
        "email": "rm1@bank.com",
        "password": "1234",
        "role_name": "RELATIONSHIP_MANAGER",
    },
    {
        "username": "admin",
        "email": "admin@bank.com",
        "password": "1234",
        "role_name": "ADMIN",
    },
]


async def reset_and_seed():
    async with AsyncSessionLocal() as db:
        print("🗑️  1. Truncating users & related audit log tables...")
        # CASCADE removes referencing rows in audit_logs and other child tables
        # RESTART IDENTITY resets primary key IDs back to 1
        await db.execute(text("TRUNCATE TABLE users RESTART IDENTITY CASCADE;"))
        await db.commit()
        print("   ✅ Database tables cleared successfully.")

        print("\n🌱 2. Seeding fresh roles and users...")
        for account in DEMO_USERS:
            # Ensure role exists in database
            role_stmt = select(Role).where(Role.role_name == account["role_name"])
            role = (await db.execute(role_stmt)).scalar_one_or_none()

            if not role:
                role = Role(
                    role_name=account["role_name"],
                    description=f"System Role for {account['role_name']}"
                )
                db.add(role)
                await db.flush()
                print(f"   + Created Role: {account['role_name']}")

            # Create fresh user with valid password hash
            new_user = User(
                username=account["username"],
                email=account["email"],
                hashed_password=get_password_hash(account["password"]),
                role_id=role.role_id,
                is_active=True,
            )
            db.add(new_user)
            print(f"   + Created User: {account['email']} (Password: {account['password']})")

        await db.commit()
        print("\n✨ 3. Reset complete! All test accounts are ready for login.")


if __name__ == "__main__":
    asyncio.run(reset_and_seed())