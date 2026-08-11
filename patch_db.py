import asyncio
from sqlalchemy import text
from app.db.session import engine

async def patch():
    columns_to_add = [
        "filename VARCHAR",
        "category VARCHAR DEFAULT 'General Policy'",
        "version VARCHAR DEFAULT '1.0'",
        "uploaded_by VARCHAR DEFAULT 'ADMIN'",
        "uploaded_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP"
    ]
    
    async with engine.begin() as conn:
        for col in columns_to_add:
            query = text(f"ALTER TABLE policy_documents ADD COLUMN IF NOT EXISTS {col};")
            await conn.execute(query)
            
    print("Database table 'policy_documents' updated successfully!")

if __name__ == "__main__":
    asyncio.run(patch())