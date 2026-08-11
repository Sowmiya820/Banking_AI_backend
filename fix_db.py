# Save as backend/fix_db.py
import asyncio
from sqlalchemy import text
from app.db.session import engine

async def repair_database_schema():
    columns_to_add = [
        "filename VARCHAR DEFAULT ''",
        "category VARCHAR DEFAULT 'General Policy'",
        "version VARCHAR DEFAULT '1.0'",
        "status VARCHAR DEFAULT 'ACTIVE'",
        "uploaded_by VARCHAR DEFAULT 'admin1'",
        "uploaded_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP"
    ]
    
    async with engine.begin() as conn:
        print("Checking and patching 'policy_documents' schema...")
        for col in columns_to_add:
            query = text(f"ALTER TABLE policy_documents ADD COLUMN IF NOT EXISTS {col};")
            await conn.execute(query)
            
    print("Database schema successfully updated!")

if __name__ == "__main__":
    asyncio.run(repair_database_schema())