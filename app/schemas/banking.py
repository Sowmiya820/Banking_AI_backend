from typing import List, Optional
from datetime import date
from pydantic import BaseModel


class TransactionSchema(BaseModel):
    txn_id: str
    account_id: int
    customer_id: int
    txn_date: Optional[date]
    value_date: Optional[date]
    amount: float
    txn_type: str
    counterparty: Optional[str] = None
    narrative: Optional[str] = None
    channel: Optional[str] = None
    is_suspicious: Optional[str] = "N"

    class Config:
        from_attributes = True


class AccountSchema(BaseModel):
    account_id: int
    customer_id: int
    category: Optional[int] = None
    currency: str
    account_title: str
    opening_date: Optional[date] = None
    working_balance: float
    posting_restrict: Optional[str] = None
    product: Optional[str] = None

    class Config:
        from_attributes = True


class LoanSchema(BaseModel):
    loan_id: str
    customer_id: int
    product: str
    currency: str
    sanctioned_amount: float
    outstanding: float
    interest_rate: float
    tenure_months: Optional[int] = None
    start_date: Optional[date] = None
    status: str
    days_past_due: Optional[int] = 0
    collateral_value: Optional[float] = 0.0
    limit_amount: Optional[float] = 0.0

    class Config:
        from_attributes = True


class LimitsCollateralSchema(BaseModel):
    limit_id: str
    customer_id: int
    limit_product: Optional[str] = None
    currency: str
    approved_limit: float
    utilized: float
    available: float

    class Config:
        from_attributes = True


class Customer360Response(BaseModel):
    customer_id: int
    mnemonic: Optional[str] = None
    short_name: Optional[str] = None
    name_1: str
    street: Optional[str] = None
    town_country: Optional[str] = None
    nationality: Optional[str] = None
    residence: Optional[str] = None
    kyc_status: str
    monthly_income: Optional[float] = 0.0
    employment_type: Optional[str] = None
    
    # Nested relations
    accounts: List[AccountSchema] = []
    loans: List[LoanSchema] = []
    limits: List[LimitsCollateralSchema] = []

    class Config:
        from_attributes = True