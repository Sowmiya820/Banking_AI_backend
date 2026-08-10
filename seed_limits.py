import os
import pandas as pd
from sqlalchemy import create_engine
from dotenv import load_dotenv

load_dotenv()

raw_db_url = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/banking_copilot")
# Convert async dialect to sync dialect for SQLAlchemy pandas seeding
DATABASE_URL = raw_db_url.replace("postgresql+asyncpg://", "postgresql://")

engine = create_engine(DATABASE_URL)

def seed_limits_collateral():
    csv_path = "data/limits_collateral.csv"
    
    # Check if CSV file exists or look in current directory
    if not os.path.exists(csv_path):
        if os.path.exists("limits_collateral.csv"):
            csv_path = "limits_collateral.csv"
        else:
            print(f"❌ Error: Could not find limits_collateral.csv in data/ or root folder.")
            return

    print(f"📥 Loading '{csv_path}' into table 'limits_collateral'...")
    df = pd.read_csv(csv_path)
    
    try:
        # Load into limits_collateral table
        df.to_sql("limits_collateral", engine, if_exists="append", index=False)
        print(f" Successfully inserted {len(df)} rows into 'limits_collateral'!")
    except Exception as e:
        print(f"❌ Error inserting rows: {e}")

if __name__ == "__main__":
    seed_limits_collateral()