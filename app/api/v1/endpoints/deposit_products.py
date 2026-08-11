import os
import json
import math
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.db.models.models import User
from app.services.audit import log_audit_event
from app.core.dependencies import require_roles

try:
    from groq import Groq
    GROQ_SDK_AVAILABLE = True
except ImportError:
    GROQ_SDK_AVAILABLE = False

router = APIRouter(prefix="/deposit-products", tags=["Module A2: Deposit Products"])

# ------------------------------------------------------------------
# CURRENCY CONFIGURATION & MAP
# ------------------------------------------------------------------
CURRENCY_SYMBOLS = {
    "INR": "₹",
    "USD": "$",
    "GBP": "£",
    "EUR": "€"
}

# ------------------------------------------------------------------
# DETERMINISTIC PRODUCT DATABASE (Normalized In-Memory / DB Store)
# ------------------------------------------------------------------
MOCK_DEPOSIT_PRODUCTS = [
    {
        "product_id": "fd_flexi_2026",
        "product_name": "Flexi Fixed Deposit",
        "category": "one_time",
        "interest_rate": 7.25,
        "rate_type": "interest_rate", # 'interest_rate' or 'apy'
        "min_amount": 10000,
        "max_amount": 10000000,
        "min_months": 12,
        "max_months": 60,
        "liquidity_level": "MEDIUM",
        "advantages": [
            "Higher guaranteed returns than regular savings",
            "Partial withdrawal allowed without breaking entire deposit",
            "Flexible tenure options from 1 to 5 years"
        ],
        "trade_offs": [
            "Early withdrawal of remaining amount reduces interest earned by 0.50%",
            "Limited instant access compared to standard savings account"
        ],
        "best_for": "Lump-sum savings for medium-term goals with partial flexibility"
    },
    {
        "product_id": "fd_max_yield_2026",
        "product_name": "High-Yield Term Deposit",
        "category": "one_time",
        "interest_rate": 7.75,
        "rate_type": "interest_rate",
        "min_amount": 25000,
        "max_amount": 50000000,
        "min_months": 24,
        "max_months": 120,
        "liquidity_level": "LOW",
        "advantages": [
            "Maximum guaranteed interest rate",
            "Compounded quarterly for higher cumulative returns",
            "Ideal for fixed long-term financial goals"
        ],
        "trade_offs": [
            "Strict lock-in period until maturity",
            "Premature withdrawal (taking money out early) incurs a 1.00% interest penalty"
        ],
        "best_for": "Long-term lump-sum goals where immediate liquidity is not required"
    },
    {
        "product_id": "rd_builder_2026",
        "product_name": "Monthly Wealth Builder RD",
        "category": "monthly",
        "interest_rate": 7.10,
        "rate_type": "interest_rate",
        "min_amount": 1000,
        "max_amount": 1000000,
        "min_months": 6,
        "max_months": 120,
        "liquidity_level": "LOW",
        "advantages": [
            "Encourages disciplined regular monthly savings habit",
            "Guaranteed fixed interest rate locked in at account opening",
            "Low minimum initial monthly deposit"
        ],
        "trade_offs": [
            "Missing monthly installments may result in a small penalty",
            "Money is locked in until maturity date"
        ],
        "best_for": "Building a targeted savings pool through disciplined monthly contributions"
    },
    {
        "product_id": "savings_liquid_plus",
        "product_name": "Liquid Plus Savings Account",
        "category": "both",
        "interest_rate": 4.50,
        "rate_type": "interest_rate",
        "min_amount": 1000,
        "max_amount": 100000000,
        "min_months": 1,
        "max_months": 120,
        "liquidity_level": "HIGH",
        "advantages": [
            "100% instant access to funds at any time with zero penalties",
            "Daily interest calculation paid quarterly",
            "No lock-in period or premature withdrawal restrictions"
        ],
        "trade_offs": [
            "Lower interest rate compared to FD (Fixed Deposit) or RD (Recurring Deposit) options",
            "Interest earned may fluctuate based on central bank benchmark updates"
        ],
        "best_for": "Emergency funds requiring 100% instant liquidity and penalty-free access"
    }
]


# ------------------------------------------------------------------
# DETERMINISTIC FINANCIAL CALCULATOR
# ------------------------------------------------------------------
def calculate_financials(
    investment_type: str,
    amount: float,
    annual_rate: float,
    tenure_months: int
) -> Dict[str, float]:
    """
    Computes exact, deterministic interest and maturity values.
    Uses Compound Interest formula for Lump-Sum (FD) and Monthly Annuity formula for RD.
    """
    r = annual_rate / 100.0
    t = tenure_months / 12.0

    if investment_type == "monthly":
        # Compound interest on regular monthly deposits (Quarterly compounding standard)
        n = 4 # quarterly compounding
        months = tenure_months
        total_deposited = amount * months
        
        # Standard RD Formula: A = P * sum((1 + r/4)^(4 * t_i))
        maturity_value = 0.0
        for m in range(1, months + 1):
            time_remaining = (months - m + 1) / 12.0
            maturity_value += amount * math.pow(1 + r/4, 4 * time_remaining)
            
        estimated_interest = max(0.0, maturity_value - total_deposited)
        return {
            "total_invested": round(total_deposited, 2),
            "estimated_interest": round(estimated_interest, 2),
            "estimated_maturity": round(maturity_value, 2)
        }
    else:
        # One-time Lump-sum deposit (Compounded quarterly)
        n = 4
        maturity_value = amount * math.pow(1 + r/n, n * t)
        estimated_interest = maturity_value - amount
        return {
            "total_invested": round(amount, 2),
            "estimated_interest": round(estimated_interest, 2),
            "estimated_maturity": round(maturity_value, 2)
        }


# ------------------------------------------------------------------
# SCHEMAS
# ------------------------------------------------------------------
class DepositAdvisorRequest(BaseModel):
    financial_goal: str = Field(..., example="Emergency Fund")
    custom_goal: Optional[str] = Field(None, example="Buying a boat")
    currency: str = Field(default="INR", example="INR")
    investment_type: str = Field(..., example="one_time") # 'one_time' or 'monthly'
    amount: float = Field(..., gt=0, example=500000)
    tenure_value: int = Field(..., gt=0, example=2)
    tenure_unit: str = Field(default="years", example="years") # 'months' or 'years'
    liquidity_requirement: str = Field(default="MEDIUM", example="MEDIUM") # 'HIGH', 'MEDIUM', 'LOW'


class ProductRecommendation(BaseModel):
    product_id: str
    product_name: str
    match_badge: str # 'Top Choice', 'Strong Match', 'Good Alternative'
    liquidity_display: str
    interest_rate_display: str
    amount_display: str
    estimated_interest_display: str
    estimated_maturity_display: str
    numeric_interest: float
    numeric_maturity: float
    advantages: List[str]
    trade_offs: List[str]
    summary_note: str


class DepositAdvisorResponse(BaseModel):
    status: str = "success"
    currency: str
    currency_symbol: str
    top_recommendation_name: str
    why_it_suits: str
    main_trade_off: str
    ranked_products: List[ProductRecommendation]
    ranking_factors: List[str]
    transparency_note: str
    evaluator: str = "Groq Financial AI Advisor"


# ------------------------------------------------------------------
# CORE RECOMMENDATION PIPELINE
# ------------------------------------------------------------------
@router.post("/recommend", response_model=DepositAdvisorResponse)
async def recommend_deposit_products(
    payload: DepositAdvisorRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(require_roles(["RELATIONSHIP MANAGER", "RELATIONSHIP_MANAGER", "LOAN OFFICER", "LOAN_OFFICER", "CUSTOMER", "ADMIN"]))
):
    # 1. Normalize Inputs
    curr_code = payload.currency.upper() if payload.currency in CURRENCY_SYMBOLS else "INR"
    curr_sym = CURRENCY_SYMBOLS.get(curr_code, "₹")
    
    selected_goal = payload.custom_goal if payload.financial_goal == "Other" and payload.custom_goal else payload.financial_goal
    tenure_months = payload.tenure_value if payload.tenure_unit.lower() == "months" else payload.tenure_value * 12

    # 2. Filter Products by Eligibility & Investment Type
    eligible_products = []
    for p in MOCK_DEPOSIT_PRODUCTS:
        # Category filter: Never recommend RD for Lump-sum or FD for Monthly
        if p["category"] != "both" and p["category"] != payload.investment_type:
            continue
        
        # Tenure suitability check
        if tenure_months < p["min_months"] or tenure_months > p["max_months"]:
            continue
            
        eligible_products.append(p)

    if not eligible_products:
        # Fallback to all matching category products if tenure filter was too restrictive
        eligible_products = [p for p in MOCK_DEPOSIT_PRODUCTS if p["category"] in [payload.investment_type, "both"]]

    # 3. Deterministic Financial Math & Scoring
    scored_products = []
    for p in eligible_products:
        fin = calculate_financials(
            investment_type=payload.investment_type,
            amount=payload.amount,
            annual_rate=p["interest_rate"],
            tenure_months=tenure_months
        )
        
        # Scoring based on Liquidity Alignment & Interest Rate
        score = p["interest_rate"] * 10.0
        if payload.liquidity_requirement.upper() == p["liquidity_level"]:
            score += 25.0
        elif payload.liquidity_requirement.upper() == "HIGH" and p["liquidity_level"] == "MEDIUM":
            score += 10.0
            
        scored_products.append({
            "details": p,
            "financials": fin,
            "score": score
        })

    # Sort descending by score
    scored_products.sort(key=lambda x: x["score"], reverse=True)

    # 4. Format Products for Response
    ranked_cards: List[ProductRecommendation] = []
    badges = ["Top Choice", "Strong Match", "Good Alternative"]

    for idx, item in enumerate(scored_products):
        p = item["details"]
        fin = item["financials"]
        badge = badges[idx] if idx < len(badges) else "Good Alternative"
        
        rate_label = f"Interest Rate: {p['interest_rate']}% p.a." if p['rate_type'] == "interest_rate" else f"APY (Annual Percentage Yield): {p['interest_rate']}%"
        
        liquidity_text = {
            "HIGH": "High — Instant access at any time",
            "MEDIUM": "Medium — Partial access allowed",
            "LOW": "Low — Limited access until maturity"
        }.get(p["liquidity_level"], "Medium access")

        ranked_cards.append(
            ProductRecommendation(
                product_id=p["product_id"],
                product_name=p["product_name"],
                match_badge=badge,
                liquidity_display=liquidity_text,
                interest_rate_display=rate_label,
                amount_display=f"{curr_sym}{payload.amount:,.2f}",
                estimated_interest_display=f"{curr_sym}{fin['estimated_interest']:,.2f}",
                estimated_maturity_display=f"{curr_sym}{fin['estimated_maturity']:,.2f}",
                numeric_interest=fin['estimated_interest'],
                numeric_maturity=fin['estimated_maturity'],
                advantages=p["advantages"],
                trade_offs=p["trade_offs"],
                summary_note=f"{p['best_for']}."
            )
        )

    top_card = ranked_cards[0]

    # 5. Invoke Groq for Plain-Language Explanation (Enforcing Acronym Rules)
    why_suits_explanation = (
        f"Your {curr_sym}{payload.amount:,.2f} {'lump-sum' if payload.investment_type == 'one_time' else 'monthly'} "
        f"investment for the '{selected_goal}' goal over {payload.tenure_value} {payload.tenure_unit} matches "
        f"{top_card.product_name} well based on your {payload.liquidity_requirement.lower()} liquidity requirement."
    )
    main_trade_off = top_card.trade_offs[0] if top_card.trade_offs else "Early withdrawal may reduce earned interest."

    groq_api_key = os.getenv("GROQ_API_KEY")
    if groq_api_key and GROQ_SDK_AVAILABLE:
        try:
            client = Groq(api_key=groq_api_key)
            prompt = f"""
You are a helpful Bank Advisor explaining a deposit recommendation to a customer.

CUSTOMER CONTEXT:
- Financial Goal: {selected_goal}
- Currency & Amount: {curr_sym}{payload.amount:,.2f} ({curr_code})
- Investment Style: {'One-time lump sum' if payload.investment_type == 'one_time' else 'Regular monthly deposit'}
- Tenure: {payload.tenure_value} {payload.tenure_unit}
- Liquidity Requirement: {payload.liquidity_requirement}

TOP RECOMMENDED PRODUCT:
- Product Name: {top_card.product_name}
- Interest: {top_card.interest_rate_display}
- Estimated Maturity: {top_card.estimated_maturity_display}
- Top Advantages: {", ".join(top_card.advantages)}
- Primary Trade-off: {main_trade_off}

CRITICAL FORMATTING & ACRONYM RULES:
1. Explain in plain, friendly language why this product suits the customer's goal and liquidity needs (2 short sentences).
2. Write the main trade-off in 1 simple sentence without technical jargon.
3. ABSOLUTE ACRONYM RULE: Whenever introducing technical acronyms for the FIRST time, write their full meaning in brackets!
   Examples: 
   - FD -> FD (Fixed Deposit)
   - RD -> RD (Recurring Deposit)
   - APY -> APY (Annual Percentage Yield)
   - KYC -> KYC (Know Your Customer)

Respond strictly in valid JSON:
{{
  "why_it_suits": "Explanation text here...",
  "main_trade_off": "Trade off explanation here..."
}}
"""
            completion = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.1
            )
            llm_res = json.loads(completion.choices[0].message.content)
            why_suits_explanation = llm_res.get("why_it_suits", why_suits_explanation)
            main_trade_off = llm_res.get("main_trade_off", main_trade_off)
        except Exception as e:
            print(f"⚠️ [Deposit Advisor LLM Fallback]: {e}")

    # Audit Log
    if db and current_user:
        try:
            await log_audit_event(
                db=db,
                user_id=current_user.user_id,
                action="DEPOSIT_PRODUCT_ADVISOR_QUERY",
                endpoint="/api/v1/deposit-products/recommend",
                details=f"Goal: {selected_goal} | Amount: {curr_sym}{payload.amount} | Type: {payload.investment_type}"
            )
        except Exception as audit_err:
            print(f"⚠️ [AUDIT WARNING]: {audit_err}")

    return DepositAdvisorResponse(
        currency=curr_code,
        currency_symbol=curr_sym,
        top_recommendation_name=top_card.product_name,
        why_it_suits=why_suits_explanation,
        main_trade_off=main_trade_off,
        ranked_products=ranked_cards,
        ranking_factors=[
            "Financial goal",
            "Investment amount",
            "Investment type (Lump-sum vs Monthly)",
            "Tenure duration",
            "Liquidity requirement",
            "Interest rate & yield",
            "Early-withdrawal conditions"
        ],
        transparency_note="Products are filtered and ranked using deterministic financial math based on your stated goal, investment style, tenure, and liquidity preference. The AI explains the results in plain language without altering core financial figures."
    )