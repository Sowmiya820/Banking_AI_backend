from datetime import date, datetime, timezone
from typing import Optional, List
from sqlalchemy import (
    String, Integer, BigInteger, Float, Boolean, Date, DateTime, 
    ForeignKey, Text, JSON, func
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.session import Base

# ==========================================
# 1. AUTHENTICATION & RBAC TABLES
# ==========================================

class Role(Base):
    __tablename__ = "roles"

    role_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    role_name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)

    users: Mapped[List["User"]] = relationship(back_populates="role")


class User(Base):
    __tablename__ = "users"

    user_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.role_id"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    role: Mapped["Role"] = relationship(back_populates="users")
    audit_logs: Mapped[List["AuditLog"]] = relationship(back_populates="user")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    log_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # FIX: Made user_id optional/nullable for unauthenticated routes
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.user_id"), nullable=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(200), nullable=False)
    details: Mapped[Optional[str]] = mapped_column(Text)
    # FIX: Added Python-side default so SQLAlchemy supplies UTC time before flushing
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(), 
        nullable=False
    )

    user: Mapped[Optional["User"]] = relationship(back_populates="audit_logs")


# ==========================================
# 2. BANKING DATASET TABLES
# ==========================================

class Customer(Base):
    __tablename__ = "customers"

    customer_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    mnemonic: Mapped[Optional[str]] = mapped_column(String(20))
    short_name: Mapped[Optional[str]] = mapped_column(String(50))
    name_1: Mapped[str] = mapped_column(String(100), nullable=False)
    street: Mapped[Optional[str]] = mapped_column(String(150))
    town_country: Mapped[Optional[str]] = mapped_column(String(100))
    nationality: Mapped[Optional[str]] = mapped_column(String(10))
    residence: Mapped[Optional[str]] = mapped_column(String(10))
    sector: Mapped[Optional[int]] = mapped_column(Integer)
    account_officer: Mapped[Optional[int]] = mapped_column(Integer)
    date_of_birth: Mapped[Optional[date]] = mapped_column(Date)
    customer_status: Mapped[Optional[int]] = mapped_column(Integer)
    kyc_status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    monthly_income: Mapped[float] = mapped_column(Float, default=0.0)
    employment_type: Mapped[Optional[str]] = mapped_column(String(50))

    accounts: Mapped[List["Account"]] = relationship(back_populates="customer")
    loans: Mapped[List["Loan"]] = relationship(back_populates="customer")
    loan_applications: Mapped[List["LoanApplication"]] = relationship(back_populates="customer")
    limits: Mapped[List["LimitsCollateral"]] = relationship(back_populates="customer")


class Account(Base):
    __tablename__ = "accounts"

    account_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.customer_id"), nullable=False, index=True)
    category: Mapped[Optional[int]] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(10), default="INR")
    account_title: Mapped[str] = mapped_column(String(100))
    opening_date: Mapped[Optional[date]] = mapped_column(Date)
    working_balance: Mapped[float] = mapped_column(Float, default=0.0)
    posting_restrict: Mapped[Optional[str]] = mapped_column(String(50))
    product: Mapped[Optional[str]] = mapped_column(String(50))

    customer: Mapped["Customer"] = relationship(back_populates="accounts")
    transactions: Mapped[List["Transaction"]] = relationship(back_populates="account")


class Loan(Base):
    __tablename__ = "loans"

    loan_id: Mapped[str] = mapped_column(String(30), primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.customer_id"), nullable=False, index=True)
    product: Mapped[str] = mapped_column(String(50))
    currency: Mapped[str] = mapped_column(String(10), default="INR")
    sanctioned_amount: Mapped[float] = mapped_column(Float, nullable=False)
    outstanding: Mapped[float] = mapped_column(Float, nullable=False)
    interest_rate: Mapped[float] = mapped_column(Float, nullable=False)
    tenure_months: Mapped[int] = mapped_column(Integer, nullable=False)
    start_date: Mapped[Optional[date]] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="CURRENT")
    days_past_due: Mapped[int] = mapped_column(Integer, default=0)
    collateral_value: Mapped[float] = mapped_column(Float, default=0.0)
    limit_amount: Mapped[float] = mapped_column(Float, default=0.0)

    customer: Mapped["Customer"] = relationship(back_populates="loans")


class LoanApplication(Base):
    __tablename__ = "loan_applications"

    application_id: Mapped[str] = mapped_column(String(30), primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.customer_id"), nullable=False, index=True)
    product: Mapped[str] = mapped_column(String(50), nullable=False)
    requested_amount: Mapped[float] = mapped_column(Float, nullable=False)
    tenure_months: Mapped[int] = mapped_column(Integer, nullable=False)
    existing_emi: Mapped[float] = mapped_column(Float, default=0.0)
    credit_score: Mapped[int] = mapped_column(Integer, nullable=False)
    purpose: Mapped[Optional[str]] = mapped_column(String(100))
    decision_label: Mapped[Optional[str]] = mapped_column(String(20))

    customer: Mapped["Customer"] = relationship(back_populates="loan_applications")


class Transaction(Base):
    __tablename__ = "transactions"

    txn_id: Mapped[str] = mapped_column(String(30), primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.account_id"), nullable=False, index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.customer_id"), nullable=False, index=True)
    txn_date: Mapped[date] = mapped_column(Date, nullable=False)
    value_date: Mapped[Optional[date]] = mapped_column(Date)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    txn_type: Mapped[str] = mapped_column(String(20))
    counterparty: Mapped[Optional[str]] = mapped_column(String(100))
    narrative: Mapped[Optional[str]] = mapped_column(Text)
    channel: Mapped[Optional[str]] = mapped_column(String(30))
    is_suspicious: Mapped[str] = mapped_column(String(5), default="N")

    account: Mapped["Account"] = relationship(back_populates="transactions")


class LimitsCollateral(Base):
    __tablename__ = "limits_collateral"

    limit_id: Mapped[str] = mapped_column(String(30), primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.customer_id"), nullable=False, index=True)
    limit_product: Mapped[Optional[str]] = mapped_column(String(50))
    currency: Mapped[str] = mapped_column(String(10), default="INR")
    approved_limit: Mapped[float] = mapped_column(Float, default=0.0)
    utilized: Mapped[float] = mapped_column(Float, default=0.0)
    available: Mapped[float] = mapped_column(Float, default=0.0)
    collateral_id: Mapped[Optional[str]] = mapped_column(String(50))
    collateral_type: Mapped[Optional[str]] = mapped_column(String(50))
    collateral_value: Mapped[float] = mapped_column(Float, default=0.0)

    customer: Mapped["Customer"] = relationship(back_populates="limits")


# ==========================================
# 3. MODULE A2: DEPOSIT PRODUCTS TABLE
# ==========================================

class DepositProduct(Base):
    __tablename__ = "deposit_products"

    product_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_name: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    interest_rate: Mapped[float] = mapped_column(Float, nullable=False)
    min_amount: Mapped[float] = mapped_column(Float, default=0.0)
    max_amount: Mapped[Optional[float]] = mapped_column(Float)
    min_tenure_months: Mapped[int] = mapped_column(Integer, default=1)
    max_tenure_months: Mapped[int] = mapped_column(Integer, default=120)
    description: Mapped[str] = mapped_column(Text)
    penalty_terms: Mapped[Optional[str]] = mapped_column(Text)


# ==========================================
# 4. MODULE A3: POLICY DOCUMENTS & RAG CHUNKS
# ==========================================

class PolicyDocument(Base):
    __tablename__ = "policy_documents"

    document_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(50))
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now()
    )

    chunks: Mapped[List["PolicyChunk"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class PolicyChunk(Base):
    __tablename__ = "policy_chunks"

    chunk_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("policy_documents.document_id", ondelete="CASCADE"), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    
    # Store float array embeddings as JSON for maximum compatibility across platforms
    embedding: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    document: Mapped["PolicyDocument"] = relationship(back_populates="chunks")