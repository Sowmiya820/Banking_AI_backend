import asyncio
from passlib.context import CryptContext
from sqlalchemy.future import select

from app.db.session import AsyncSessionLocal, engine
from app.db.models.models import Base, User, Role, ModulePermission

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    return pwd_context.hash(password)


async def seed_data():
    print("⏳ Creating database tables if they don't exist...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        print("🌱 Seeding Roles...")
        roles = [
            ("ADMIN", "System Administrator with full access"),
            ("LOAN_OFFICER", "Loan Officer - Access to Module A1 & A3"),
            ("RELATIONSHIP_MANAGER", "Relationship Manager - Access to Module A2 & A4"),
        ]

        role_map = {}
        for role_name, description in roles:
            stmt = select(Role).where(Role.role_name == role_name)
            result = await db.execute(stmt)
            existing_role = result.scalars().first()

            if not existing_role:
                new_role = Role(role_name=role_name, description=description)
                db.add(new_role)
                await db.flush()
                role_map[role_name] = new_role
                print(f"   ✓ Created Role: {role_name}")
            else:
                role_map[role_name] = existing_role

        print("🌱 Seeding Module Permissions...")
        default_permissions = [
            ("ADMIN", "A1", True), ("ADMIN", "A2", True), ("ADMIN", "A3", True), ("ADMIN", "A4", True),
            ("LOAN_OFFICER", "A1", True), ("LOAN_OFFICER", "A2", False), ("LOAN_OFFICER", "A3", True), ("LOAN_OFFICER", "A4", False),
            ("RELATIONSHIP_MANAGER", "A1", False), ("RELATIONSHIP_MANAGER", "A2", True), ("RELATIONSHIP_MANAGER", "A3", True), ("RELATIONSHIP_MANAGER", "A4", True),
        ]

        for r_name, m_code, is_allowed in default_permissions:
            stmt = select(ModulePermission).where(
                ModulePermission.role_name == r_name,
                ModulePermission.module_code == m_code
            )
            res = await db.execute(stmt)
            perm = res.scalars().first()

            if not perm:
                db.add(ModulePermission(role_name=r_name, module_code=m_code, is_allowed=is_allowed))

        print("🌱 Seeding Default Admin User...")
        stmt = select(User).where(User.username == "admin")
        result = await db.execute(stmt)
        admin_user = result.scalars().first()

        if not admin_user:
            admin_user = User(
                username="admin",
                email="admin@bank.com",
                hashed_password=hash_password("AdminPass123!"),
                is_active=True,
                role_id=role_map["ADMIN"].role_id
            )
            db.add(admin_user)
            print("   ✓ Created Admin User: 'admin' (Password: AdminPass123!)")
        else:
            print("   ℹ Admin user already exists.")

        await db.commit()
        print("\n✅ DATABASE SEEDING COMPLETED SUCCESSFULLY!\n")


if __name__ == "__main__":
    asyncio.run(seed_data())