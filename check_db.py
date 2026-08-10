import asyncio
from dotenv import load_dotenv

load_dotenv()

from app.core.config import settings
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def main():
    print("🔌 Connecting to database...")
    engine = create_async_engine(settings.DATABASE_URL)
    
    async with engine.connect() as conn:
        # Fetch the table columns
        cols_res = await conn.execute(
            text("SELECT column_name FROM information_schema.columns WHERE table_name = 'loan_applications'")
        )
        columns = [row[0] for row in cols_res.fetchall()]
        print(f"📋 Columns in 'loan_applications': {columns}\n")

        # Fetch sample rows
        result = await conn.execute(text("SELECT * FROM loan_applications LIMIT 10"))
        rows = result.mappings().all()

        print("==========================================")
        print("         VALID LOAN APPLICATIONS          ")
        print("==========================================")
        for row in rows:
            print(dict(row))
        print("==========================================\n")

if __name__ == "__main__":
    asyncio.run(main())