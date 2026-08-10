import os
import pandas as pd
from sqlalchemy import create_engine
from app.core.config import settings

# 1. Database Connection Engine (using standard synchronous psycopg2 for fast bulk inserts)
# Convert async driver URL (postgresql+asyncpg://) to sync URL (postgresql://) if needed
db_url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
engine = create_engine(db_url)

# Path to the directory where your CSV files are saved
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

def clean_and_format_df(df: pd.DataFrame) -> pd.DataFrame:
    """Helper to clean headers and replace empty strings/NaNs with None for SQL NULLs."""
    df.columns = df.columns.str.strip().str.lower()
    df = df.where(pd.notnull(df), None)
    return df

def ingest_dataset(csv_filename: str, table_name: str):
    file_path = os.path.join(DATA_DIR, csv_filename)
    if not os.path.exists(file_path):
        print(f"⚠️  Skipping: {csv_filename} not found in {DATA_DIR}")
        return

    print(f"--> Ingesting {csv_filename} into '{table_name}' table...")
    df = pd.read_csv(file_path)
    df = clean_and_format_df(df)

    # Fast bulk insert into PostgreSQL table
    df.to_sql(
        name=table_name,
        con=engine,
        if_exists="append",  # Options: 'append' to add rows, 'replace' to drop/recreate
        index=False,
        chunksize=1000       # Process in batches for high performance
    )
    print(f"✅ Ingested {len(df)} records into '{table_name}'.")

def main():
    print("==========================================")
    print(" Starting Banking CSV Dataset Ingestion ")
    print("==========================================")

    # Enforce order due to Foreign Key dependencies
    files_to_tables = [
        ("customers.csv", "customers"),
        ("accounts.csv", "accounts"),
        ("loans.csv", "loans"),
        ("loan_applications.csv", "loan_applications"),
        ("transactions.csv", "transactions"),
    ]

    for csv_file, table_name in files_to_tables:
        try:
            ingest_dataset(csv_file, table_name)
        except Exception as e:
            print(f"❌ Error ingesting {csv_file}: {e}")

    print("\n==========================================")
    print(" Ingestion Completed Successfully! ")
    print("==========================================")

if __name__ == "__main__":
    main()