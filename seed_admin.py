import asyncio
import sys

print("=== STARTING SEED SCRIPT ===")

try:
    from app.db.session import AsyncSessionLocal
    from app.core.security import get_password_hash, verify_password
    from sqlalchemy import text
    print("=== BACKEND MODULES LOADED ===")
except Exception as e:
    print("IMPORT ERROR:", e)
    sys.exit(1)

async def run_seed():
    print("=== CONNECTING TO DATABASE ===")
    async with AsyncSessionLocal() as session:
        # 1. Ensure ADMIN role exists (role_id = 1)
        await session.execute(text("""
            INSERT INTO roles (role_id, role_name, description)
            VALUES (1, 'ADMIN', 'System Administrator')
            ON CONFLICT (role_name) DO NOTHING;
        """))
        
        # 2. Insert or update Admin User
        pwd_hash = get_password_hash("AdminSecurePassword123!")
        await session.execute(text("""
            INSERT INTO users (username, email, hashed_password, role_id, is_active)
            VALUES ('admin', 'admin@bank.com', :pwd, 1, true)
            ON CONFLICT (username)
            DO UPDATE SET hashed_password = :pwd, is_active = true;
        """), {"pwd": pwd_hash})
        
        await session.commit()
        
        # 3. Verify
        res = await session.execute(text("SELECT username, hashed_password FROM users WHERE username = 'admin'"))
        row = res.fetchone()
        
        if row:
            is_valid = verify_password("AdminSecurePassword123!", row[1])
            print("\n" + "="*50)
            print(" SUCCESS! Admin user created in PostgreSQL.")
            print(" Username: admin")
            print(" Password: AdminSecurePassword123!")
            print(" Password Validated:", is_valid)
            print("="*50 + "\n")
        else:
            print("ERROR: User not created.")

if __name__ == "__main__":
    asyncio.run(run_seed())