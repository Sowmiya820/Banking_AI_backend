from fastapi import APIRouter
from app.api.v1.endpoints import (
    auth,
    loan_copilot,      # Module A1: AI Loan Officer
    deposit_products,  # Module A2: Deposit Product Advisor
    policy_explainer,  # Module A3: Bank Policy Explainer
    letter_writer,     # Module A4: Bank Letter Writer
    banking,           # Core Banking Operations
)

api_router = APIRouter()

# 1. Authentication Endpoints -> /api/v1/auth
api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])

# 2. Core Banking Endpoints -> /api/v1/banking
api_router.include_router(banking.router, prefix="/banking", tags=["Banking Core"])

# 3. AI Copilot Modules (Prefixes are defined inside each endpoint router file)
api_router.include_router(loan_copilot.router, tags=["Module A1: Loan Copilot"])
api_router.include_router(deposit_products.router, tags=["Module A2: Deposit Product Advisor"])
api_router.include_router(policy_explainer.router, tags=["Module A3: Bank Policy Explainer"])
api_router.include_router(letter_writer.router, tags=["Module A4: Bank Letter Writer"])