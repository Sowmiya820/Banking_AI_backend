import os
import json
from pathlib import Path
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
import pandas as pd

from app.db.session import get_db
from app.db.models.models import DepositProduct
from app.services.audit import log_audit_event

# Safe Groq SDK import check
try:
    from groq import Groq
    GROQ_SDK_AVAILABLE = True
except ImportError:
    GROQ_SDK_AVAILABLE = False

router = APIRouter(prefix="/deposit-products", tags=["Module A2: Deposit Product Advisor"])

# ------------------------------------------------------------------
# RAG Tier 3: In-Memory Static Fallback Catalog
# ------------------------------------------------------------------
FALLBACK_DEPOSIT_PRODUCTS = [
    {
        "product_id": "HYSA-01",
        "product_name": "High-Yield Savings Account",
        "category": "Savings",
        "apy": 4.85,
        "min_amount": 100.0,
        "max_tenure_months": 120,
        "liquidity_level": "High (Instant access)",
        "lock_in": False,
        "early_withdrawal_penalty": "None",
        "risk_level": "Very Low (FDIC Insured)",
        "best_for": "Emergency Fund, Short-term Cash"
    },
    {
        "product_id": "CD-SHORT-06",
        "product_name": "6-Month Certificate of Deposit (CD)",
        "category": "Fixed",
        "apy": 5.25,
        "min_amount": 1000.0,
        "max_tenure_months": 6,
        "liquidity_level": "Low (Locked for 6 mo)",
        "lock_in": True,
        "early_withdrawal_penalty": "3 months interest",
        "risk_level": "Very Low (FDIC Insured)",
        "best_for": "Short-Term Saving, Guaranteed Yield"
    },
    {
        "product_id": "CD-LONG-12",
        "product_name": "12-Month Fixed Deposit / CD",
        "category": "FD",
        "apy": 5.40,
        "min_amount": 500.0,
        "max_tenure_months": 12,
        "liquidity_level": "Low (Locked for 12 mo)",
        "lock_in": True,
        "early_withdrawal_penalty": "6 months interest",
        "risk_level": "Very Low (FDIC Insured)",
        "best_for": "Wealth Growth, Capital Preservation"
    },
    {
        "product_id": "MMA-01",
        "product_name": "Premier Money Market Account",
        "category": "Savings",
        "apy": 4.60,
        "min_amount": 5000.0,
        "max_tenure_months": 120,
        "liquidity_level": "Moderate (Debit card/Check access)",
        "lock_in": False,
        "early_withdrawal_penalty": "None",
        "risk_level": "Very Low (FDIC Insured)",
        "best_for": "Large Liquid Balances, Flexible Savings"
    },
    {
        "product_id": "FLEXI-RD-24",
        "product_name": "24-Month Flexi Recurring Deposit",
        "category": "RD",
        "apy": 5.15,
        "min_amount": 250.0,
        "max_tenure_months": 24,
        "liquidity_level": "Moderate (Partial withdrawal allowed)",
        "lock_in": True,
        "early_withdrawal_penalty": "0.5% interest deduction",
        "risk_level": "Very Low (FDIC Insured)",
        "best_for": "Education Fund, Periodic Savings"
    }
]


# ------------------------------------------------------------------
# SCHEMAS
# ------------------------------------------------------------------
class DepositRecommendationRequest(BaseModel):
    financial_goal: str = Field(..., example="Save for higher education")
    deposit_amount: float = Field(..., gt=0, example=10000.0)
    tenure_months: int = Field(..., gt=0, example=24)
    liquidity_needed: Optional[bool] = Field(default=True, example=True)


class TradeOffBreakdownItem(BaseModel):
    product_name: str
    pros: List[str]
    cons: List[str]
    trade_off_note: str


class LLMAnalysisResponse(BaseModel):
    recommended_option: str
    executive_summary: str
    trade_off_breakdown: List[TradeOffBreakdownItem]
    key_takeaway: str


class DepositRecommendationResponse(BaseModel):
    status: str
    evaluator: str
    inputs: Dict[str, Any]
    recommended_products: List[Dict[str, Any]]
    analysis: LLMAnalysisResponse


# ------------------------------------------------------------------
# RAG RETRIEVAL ENGINE (Database -> CSV File -> Fallback Memory)
# ------------------------------------------------------------------
async def retrieve_grounded_products(
    deposit_amount: float,
    tenure_months: int,
    db: AsyncSession
) -> List[Dict[str, Any]]:
    """
    Structured RAG Retriever: Searches active product store based on
    financial constraints (min_amount & max_tenure_months).
    """
    retrieved_products: List[Dict[str, Any]] = []

    # Tier 1: Primary RAG Retrieval from PostgreSQL Database
    try:
        stmt = select(DepositProduct).where(DepositProduct.min_amount <= deposit_amount)
        result = await db.execute(stmt)
        products_db = result.scalars().all()

        if products_db:
            for p in products_db:
                retrieved_products.append({
                    "product_id": getattr(p, "product_id", getattr(p, "id", f"DP-{p.id}")),
                    "product_name": getattr(p, "product_name", getattr(p, "name", "Deposit Option")),
                    "category": getattr(p, "category", "Savings"),
                    "apy": float(getattr(p, "apy", getattr(p, "interest_rate", 4.5))),
                    "min_amount": float(getattr(p, "min_amount", 0.0)),
                    "max_tenure_months": int(getattr(p, "max_tenure_months", 120)),
                    "liquidity_level": getattr(p, "liquidity_level", "Moderate"),
                    "lock_in": bool(getattr(p, "lock_in", False)),
                    "early_withdrawal_penalty": getattr(p, "early_withdrawal_penalty", "None"),
                    "risk_level": getattr(p, "risk_level", "Very Low"),
                    "best_for": getattr(p, "best_for", "Goal Growth")
                })
    except Exception as e:
        print(f"⚠️ [RAG DB RETRIEVAL WARNING] Database query failed: {e}")

    # Tier 2: Secondary RAG Retrieval from Local CSV File (if DB returned no matches)
    if not retrieved_products:
        csv_paths = [
            Path("data/deposit_products.csv"),
            Path("backend/data/deposit_products.csv"),
            Path("app/data/deposit_products.csv")
        ]
        for path in csv_paths:
            if path.exists():
                try:
                    df = pd.read_csv(path)
                    df.columns = df.columns.str.strip().str.lower()
                    records = df.to_dict(orient="records")
                    for r in records:
                        if float(r.get("min_amount", 0.0)) <= deposit_amount:
                            retrieved_products.append({
                                "product_id": str(r.get("product_id", "CSV-01")),
                                "product_name": str(r.get("product_name", "Deposit Option")),
                                "category": str(r.get("category", "Savings")),
                                "apy": float(r.get("apy", 4.5)),
                                "min_amount": float(r.get("min_amount", 0.0)),
                                "max_tenure_months": int(r.get("max_tenure_months", 120)),
                                "liquidity_level": str(r.get("liquidity_level", "Moderate")),
                                "lock_in": bool(r.get("lock_in", False)),
                                "early_withdrawal_penalty": str(r.get("early_withdrawal_penalty", "None")),
                                "risk_level": str(r.get("risk_level", "Very Low")),
                                "best_for": str(r.get("best_for", "Savings Goal"))
                            })
                    if retrieved_products:
                        break
                except Exception as csv_err:
                    print(f"⚠️ [RAG CSV RETRIEVAL WARNING] Failed reading CSV: {csv_err}")

    # Tier 3: Tertiary RAG Retrieval from In-Memory Catalog
    if not retrieved_products:
        retrieved_products = [
            p for p in FALLBACK_DEPOSIT_PRODUCTS
            if deposit_amount >= p["min_amount"]
        ]

    return retrieved_products


# ------------------------------------------------------------------
# LLM TRADE-OFF GENERATOR (Augment + Generate)
# ------------------------------------------------------------------
def analyze_tradeoffs_with_groq(
    goal: str,
    amount: float,
    tenure: int,
    liquidity_needed: bool,
    ranked_products: List[dict]
) -> Optional[Dict[str, Any]]:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key or not GROQ_SDK_AVAILABLE:
        return None

    try:
        client = Groq(api_key=api_key)

        system_prompt = (
            "You are an expert Banking Wealth & Deposit Product Advisor.\n"
            "Analyze deposit product options for a customer's specific goal and perform a trade-off comparison.\n"
            "Return STRICT JSON with no markdown block wrappers around the JSON output:\n"
            "{\n"
            '  "recommended_option": "Name of top recommended product",\n'
            '  "executive_summary": "2-3 sentences explaining why this option best fits their goal.",\n'
            '  "trade_off_breakdown": [\n'
            '     {"product_name": "Product Name", "pros": ["Pro 1", "Pro 2"], "cons": ["Con 1"], "trade_off_note": "Plain language comparison"}\n'
            "  ],\n"
            '  "key_takeaway": "Actionable closing guidance for the customer."\n'
            "}"
        )

        user_prompt = f"""
        CUSTOMER CONSTRAINTS:
        - Financial Goal: {goal}
        - Deposit Amount: ${amount:,.2f}
        - Desired Tenure: {tenure} months
        - Liquidity Access Required: {'Yes' if liquidity_needed else 'No'}

        RETRIEVED GROUNDED PRODUCTS (RAG CONTEXT):
        {json.dumps(ranked_products, indent=2)}

        Provide strict recommendations grounded only in the provided product context.
        """

        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=850
        )

        return json.loads(response.choices[0].message.content)
    except Exception as e:
        print(f"⚠️ [GROQ DEPOSIT ENGINE WARNING] {e}. Falling back to deterministic engine.")
        return None


# ------------------------------------------------------------------
# ROUTE ENDPOINTS
# ------------------------------------------------------------------
@router.get("", response_model=List[Dict[str, Any]])
@router.get("/deposit-products", response_model=List[Dict[str, Any]])
async def get_deposit_products(
    category: Optional[str] = Query(None, description="Filter by Savings, Fixed, FD, RD, etc."),
    min_amount: Optional[float] = Query(None, description="Filter products accessible within customer budget"),
    db: AsyncSession = Depends(get_db)
):
    """Fetch active deposit catalog with optional filtering and audit logging."""
    products = await retrieve_grounded_products(
        deposit_amount=min_amount or 999999999.0,
        tenure_months=120,
        db=db
    )

    if category:
        products = [p for p in products if category.lower() in p["category"].lower()]
    if min_amount is not None:
        products = [p for p in products if p["min_amount"] <= min_amount]

    try:
        await log_audit_event(
            db=db,
            action="VIEW_DEPOSIT_PRODUCTS",
            endpoint="/api/v1/deposit-products",
            details=f"Fetched {len(products)} deposit products"
        )
    except Exception as e:
        print(f"⚠️ [AUDIT LOG WARNING] Failed to record audit log: {e}")

    return products


@router.post("/recommend", response_model=DepositRecommendationResponse)
async def recommend_deposit_options(
    payload: DepositRecommendationRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Module A2 AI Deposit Product Advisor:
    1. RAG Retrieval: Queries eligible deposit products matching customer amount/tenure constraints.
    2. Deterministic Yield Math: Computes total interest and final payout per option.
    3. LLM Trade-Off Generation: Uses Groq (llama-3.3-70b-versatile) to produce grounded pros/cons and rationale.
    """
    # 1. RAG Retrieval Step
    eligible = await retrieve_grounded_products(
        deposit_amount=payload.deposit_amount,
        tenure_months=payload.tenure_months,
        db=db
    )

    if not eligible:
        raise HTTPException(
            status_code=400,
            detail=f"No suitable deposit products found for ${payload.deposit_amount:,.2f} deposit."
        )

    # 2. Deterministic Financial Yield Engine
    evaluated_products = []
    for p in eligible:
        rate = p["apy"] / 100.0
        tenure_years = payload.tenure_months / 12.0
        projected_interest = payload.deposit_amount * rate * tenure_years
        total_payout = payload.deposit_amount + projected_interest

        evaluated_products.append({
            **p,
            "projected_interest_earned": round(projected_interest, 2),
            "projected_total_payout": round(total_payout, 2)
        })

    # Sort candidates by yield (highest APY first)
    evaluated_products.sort(key=lambda x: x["apy"], reverse=True)

    # 3. RAG Generation Step: Groq Trade-Off Analysis
    liquidity_pref = payload.liquidity_needed if payload.liquidity_needed is not None else True
    llm_analysis = analyze_tradeoffs_with_groq(
        goal=payload.financial_goal,
        amount=payload.deposit_amount,
        tenure=payload.tenure_months,
        liquidity_needed=liquidity_pref,
        ranked_products=evaluated_products
    )

    # Deterministic Rule Fallback (if Groq SDK/API call fails)
    if not llm_analysis:
        top_yield_option = evaluated_products[0]
        liquid_option = next(
            (p for p in evaluated_products if not p["lock_in"]),
            evaluated_products[-1]
        )

        chosen = liquid_option if liquidity_pref and liquid_option["apy"] >= 4.5 else top_yield_option

        fallback_summary = (
            f"For your '{payload.financial_goal}' goal over {payload.tenure_months} months, {chosen['product_name']} "
            f"provides an optimal balance. It earns ${chosen['projected_interest_earned']:,.2f} at {chosen['apy']}% APY "
            f"while aligning with your liquidity expectations."
        )

        trade_offs = []
        for p in evaluated_products[:3]:
            trade_offs.append({
                "product_name": p["product_name"],
                "pros": [f"Yield: ${p['projected_interest_earned']:,.2f} ({p['apy']}% APY)", f"Risk: {p['risk_level']}"],
                "cons": [f"Early withdrawal penalty: {p['early_withdrawal_penalty']}" if p["lock_in"] else "Variable rate flexibility"],
                "trade_off_note": f"{'Guaranteed rate with locked capital' if p['lock_in'] else 'Immediate liquidity without penalties'}."
            })

        llm_analysis = {
            "recommended_option": chosen["product_name"],
            "executive_summary": fallback_summary,
            "trade_off_breakdown": trade_offs,
            "key_takeaway": "Choose fixed deposit options for maximum yield if liquidity is unneeded; otherwise select high-yield flexible savings."
        }

    # Audit Logging
    try:
        await log_audit_event(
            db=db,
            action="RECOMMEND_DEPOSIT_PRODUCT",
            endpoint="/api/v1/deposit-products/recommend",
            details=f"Generated deposit recommendations for ${payload.deposit_amount:,.2f} over {payload.tenure_months} months (Goal: '{payload.financial_goal}')"
        )
    except Exception as e:
        print(f"⚠️ [AUDIT LOG WARNING] Failed to record audit log: {e}")

    return DepositRecommendationResponse(
        status="success",
        evaluator="Groq LLM (llama-3.3-70b-versatile)" if GROQ_SDK_AVAILABLE and os.getenv("GROQ_API_KEY") else "Rule Engine (Fallback)",
        inputs={
            "financial_goal": payload.financial_goal,
            "deposit_amount": payload.deposit_amount,
            "tenure_months": payload.tenure_months,
            "liquidity_needed": liquidity_pref
        },
        recommended_products=evaluated_products,
        analysis=llm_analysis
    )