import os
import csv
import asyncio
from datetime import datetime
from sqlalchemy import select
from app.db.session import AsyncSessionLocal
from app.db.models.models import Customer, Account, Loan, Transaction, LimitsCollateral

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


def parse_date(val: str):
    """Safely parse date strings (YYYY-MM-DD)."""
    if not val or val.strip() == "":
        return None
    try:
        return datetime.strptime(val.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_float(val: str, default: float = 0.0) -> float:
    if not val or val.strip() == "":
        return default
    try:
        return float(val)
    except ValueError:
        return default


def parse_int(val: str, default: int = 0) -> int:
    if not val or val.strip() == "":
        return default
    try:
        return int(float(val))
    except ValueError:
        return default


async def seed_customers(session):
    filepath = os.path.join(DATA_DIR, "customers.csv")
    if not os.path.exists(filepath):
        print("⚠️ customers.csv not found, skipping...")
        return

    with open(filepath, mode="r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        count = 0
        for row in reader:
            cid = parse_int(row.get("customer_id"))
            res = await session.execute(select(Customer).where(Customer.customer_id == cid))
            if res.scalar_one_or_none():
                continue

            cust = Customer(
                customer_id=cid,
                mnemonic=row.get("mnemonic"),
                short_name=row.get("short_name"),
                name_1=row.get("name_1") or f"Customer {cid}",
                street=row.get("street"),
                town_country=row.get("town_country"),
                nationality=row.get("nationality"),
                residence=row.get("residence"),
                sector=parse_int(row.get("sector")) if row.get("sector") else None,
                account_officer=parse_int(row.get("account_officer")) if row.get("account_officer") else None,
                date_of_birth=parse_date(row.get("date_of_birth")),
                customer_status=parse_int(row.get("customer_status")) if row.get("customer_status") else None,
                kyc_status=row.get("kyc_status") or "PENDING",
                monthly_income=parse_float(row.get("monthly_income")),
                employment_type=row.get("employment_type")
            )
            session.add(cust)
            count += 1
        await session.commit()
        print(f"✅ Loaded {count} customers from CSV.")


async def seed_accounts(session):
    filepath = os.path.join(DATA_DIR, "accounts.csv")
    if not os.path.exists(filepath):
        print("⚠️ accounts.csv not found, skipping...")
        return

    with open(filepath, mode="r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        count = 0
        for row in reader:
            acc_id = parse_int(row.get("account_id"))
            res = await session.execute(select(Account).where(Account.account_id == acc_id))
            if res.scalar_one_or_none():
                continue

            acc = Account(
                account_id=acc_id,
                customer_id=parse_int(row.get("customer_id")),
                category=parse_int(row.get("category")) if row.get("category") else None,
                currency=row.get("currency") or "INR",
                account_title=row.get("account_title") or f"Account {acc_id}",
                opening_date=parse_date(row.get("opening_date")),
                working_balance=parse_float(row.get("working_balance")),
                posting_restrict=row.get("posting_restrict"),
                product=row.get("product")
            )
            session.add(acc)
            count += 1
        await session.commit()
        print(f"✅ Loaded {count} accounts from CSV.")


async def seed_loans(session):
    filepath = os.path.join(DATA_DIR, "loans.csv")
    if not os.path.exists(filepath):
        print("⚠️ loans.csv not found, skipping...")
        return

    with open(filepath, mode="r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        count = 0
        for row in reader:
            loan_id = str(row.get("loan_id")).strip()
            res = await session.execute(select(Loan).where(Loan.loan_id == loan_id))
            if res.scalar_one_or_none():
                continue

            loan = Loan(
                loan_id=loan_id,
                customer_id=parse_int(row.get("customer_id")),
                product=row.get("product") or "PERSONAL_LOAN",
                currency=row.get("currency") or "INR",
                sanctioned_amount=parse_float(row.get("sanctioned_amount")),
                outstanding=parse_float(row.get("outstanding")),
                interest_rate=parse_float(row.get("interest_rate")),
                tenure_months=parse_int(row.get("tenure_months")),
                start_date=parse_date(row.get("start_date")),
                status=row.get("status") or "CURRENT",
                days_past_due=parse_int(row.get("days_past_due")),
                collateral_value=parse_float(row.get("collateral_value")),
                limit_amount=parse_float(row.get("limit_amount"))
            )
            session.add(loan)
            count += 1
        await session.commit()
        print(f"✅ Loaded {count} loans from CSV.")


async def seed_transactions(session):
    filepath = os.path.join(DATA_DIR, "transactions.csv")
    if not os.path.exists(filepath):
        print("⚠️ transactions.csv not found, skipping...")
        return

    with open(filepath, mode="r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        count = 0
        for row in reader:
            txn_id = str(row.get("txn_id")).strip()
            res = await session.execute(select(Transaction).where(Transaction.txn_id == txn_id))
            if res.scalar_one_or_none():
                continue

            txn = Transaction(
                txn_id=txn_id,
                account_id=parse_int(row.get("account_id")),
                customer_id=parse_int(row.get("customer_id")),
                txn_date=parse_date(row.get("txn_date")),
                value_date=parse_date(row.get("value_date")),
                amount=parse_float(row.get("amount")),
                txn_type=row.get("txn_type"),
                counterparty=row.get("counterparty"),
                narrative=row.get("narrative"),
                channel=row.get("channel"),
                is_suspicious=row.get("is_suspicious") or "N"
            )
            session.add(txn)
            count += 1
        await session.commit()
        print(f"✅ Loaded {count} transactions from CSV.")


async def main():
    async with AsyncSessionLocal() as session:
        print("⏳ Ingesting CSV files from backend/data/...")
        await seed_customers(session)
        await seed_accounts(session)
        await seed_loans(session)
        await seed_transactions(session)
        print("🎉 Module A1 dataset ingestion complete!")


if __name__ == "__main__":
    asyncio.run(main())