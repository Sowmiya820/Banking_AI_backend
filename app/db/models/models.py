from datetime import date, datetime, timezone
from typing import Any, List, Optional
from sqlalchemy import (
    String, Integer, BigInteger, Float, Boolean, Date, DateTime, 
    ForeignKey, Text, JSON, UniqueConstraint, func
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.session import Base


# ==========================================
# 1. AUTHENTICATION & RBAC TABLES
# ==========================================

class Role(Base):
    __tablename__ = "roles"

    role_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    role_name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    users: Mapped[List["User"]] = relationship(back_populates="role")


class User(Base):
    __tablename__ = "users"

    user_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.role_id"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    role: Mapped["Role"] = relationship(back_populates="users")
    audit_logs: Mapped[List["AuditLog"]] = relationship(back_populates="user")


class ModulePermission(Base):
    """Stores Application-Level Access permissions (A1, A2, A3, A4) per Role."""
    __tablename__ = "module_permissions"
    __table_args__ = (
        UniqueConstraint("role_name", "module_code", name="uq_role_module"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    role_name: Mapped[str] = mapped_column(String(50), nullable=False, index=True)  # ADMIN, LOAN_OFFICER, RELATIONSHIP_MANAGER
    module_code: Mapped[str] = mapped_column(String(10), nullable=False)             # A1, A2, A3, A4
    is_allowed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        server_default=func.now(), 
        nullable=False
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    log_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.user_id"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(200), nullable=False)
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
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
    mnemonic: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    short_name: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    name_1: Mapped[str] = mapped_column(String(100), nullable=False)
    street: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    town_country: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    nationality: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    residence: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    sector: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    account_officer: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    date_of_birth: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    customer_status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    kyc_status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    monthly_income: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    employment_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    accounts: Mapped[List["Account"]] = relationship(back_populates="customer")
    loans: Mapped[List["Loan"]] = relationship(back_populates="customer")
    loan_applications: Mapped[List["LoanApplication"]] = relationship(back_populates="customer")
    limits: Mapped[List["LimitsCollateral"]] = relationship(back_populates="customer")


class Account(Base):
    __tablename__ = "accounts"

    account_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.customer_id"), nullable=False, index=True)
    category: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    currency: Mapped[str] = mapped_column(String(10), default="INR", nullable=False)
    account_title: Mapped[str] = mapped_column(String(100), nullable=False)
    opening_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    working_balance: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    posting_restrict: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    product: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    customer: Mapped["Customer"] = relationship(back_populates="accounts")
    transactions: Mapped[List["Transaction"]] = relationship(back_populates="account")


class Loan(Base):
    __tablename__ = "loans"

    loan_id: Mapped[str] = mapped_column(String(30), primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.customer_id"), nullable=False, index=True)
    product: Mapped[str] = mapped_column(String(50), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="INR", nullable=False)
    sanctioned_amount: Mapped[float] = mapped_column(Float, nullable=False)
    outstanding: Mapped[float] = mapped_column(Float, nullable=False)
    interest_rate: Mapped[float] = mapped_column(Float, nullable=False)
    tenure_months: Mapped[int] = mapped_column(Integer, nullable=False)
    start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="CURRENT", nullable=False)
    days_past_due: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    collateral_value: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    limit_amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    customer: Mapped["Customer"] = relationship(back_populates="loans")


class LoanApplication(Base):
    __tablename__ = "loan_applications"

    application_id: Mapped[str] = mapped_column(String(30), primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.customer_id"), nullable=False, index=True)
    product: Mapped[str] = mapped_column(String(50), nullable=False)
    requested_amount: Mapped[float] = mapped_column(Float, nullable=False)
    tenure_months: Mapped[int] = mapped_column(Integer, nullable=False)
    existing_emi: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    credit_score: Mapped[int] = mapped_column(Integer, nullable=False)
    purpose: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    decision_label: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    customer: Mapped["Customer"] = relationship(back_populates="loan_applications")


class Transaction(Base):
    __tablename__ = "transactions"

    txn_id: Mapped[str] = mapped_column(String(30), primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.account_id"), nullable=False, index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.customer_id"), nullable=False, index=True)
    txn_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    value_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    txn_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    counterparty: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    narrative: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    channel: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    is_suspicious: Mapped[str] = mapped_column(String(5), default="N", nullable=False)

    account: Mapped["Account"] = relationship(back_populates="transactions")


class LimitsCollateral(Base):
    __tablename__ = "limits_collateral"

    limit_id: Mapped[str] = mapped_column(String(30), primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.customer_id"), nullable=False, index=True)
    limit_product: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), default="INR", nullable=False)
    approved_limit: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    utilized: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    available: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    collateral_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    collateral_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    collateral_value: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

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
    min_amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    max_amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    min_tenure_months: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    max_tenure_months: Mapped[int] = mapped_column(Integer, default=120, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    penalty_terms: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


# ==========================================
# 4. MODULE A3: POLICY DOCUMENTS & RAG CHUNKS
# ==========================================

class PolicyDocument(Base):
    __tablename__ = "policy_documents"

    document_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, default="General Policy")
    file_path: Mapped[str] = mapped_column(Text, nullable=False)  # Text handles long filesystem paths
    version: Mapped[str] = mapped_column(String(50), nullable=False, default="1.0")
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="ACTIVE")  # ACTIVE, ARCHIVED
    uploaded_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False
    )

    chunks: Mapped[List["PolicyChunk"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class PolicyChunk(Base):
    __tablename__ = "policy_chunks"

    chunk_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("policy_documents.document_id", ondelete="CASCADE"), nullable=False, index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    
    # Store float array vector embeddings in JSON format for cross-platform support
    embedding: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)

    document: Mapped["PolicyDocument"] = relationship(back_populates="chunks")