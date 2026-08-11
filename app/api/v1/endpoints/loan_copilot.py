import os
import json
import time
import traceback
from pathlib import Path
from typing import List, Optional, Dict, Any
from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
import pandas as pd
from groq import Groq
from dotenv import load_dotenv

from app.core.dependencies import require_roles
from app.db.models.models import User

router = APIRouter(prefix="/loan-copilot", tags=["Loan Officer Copilot"])

# ------------------------------------------------------------------
# Path Resolution & Environment Setup
# ------------------------------------------------------------------
CURRENT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = CURRENT_DIR.parent.parent.parent.parent
ENV_PATH = BACKEND_DIR / ".env"

load_dotenv(dotenv_path=ENV_PATH)

DATA_SEARCH_DIRS = [
    BACKEND_DIR / "data",
    BACKEND_DIR / "app" / "data",
    Path("data"),
    Path("backend/data"),
]

_DATASET_CACHE: Dict[str, Dict[str, Any]] = {}


# ------------------------------------------------------------------
# Helper Functions & Multi-CSV Loader
# ------------------------------------------------------------------
def locate_csv_file(filename: str) -> Optional[Path]:
    for base_dir in DATA_SEARCH_DIRS:
        target = base_dir / filename
        if target.exists():
            return target
    return None


def load_dataset(filename: str) -> List[dict]:
    """Loads and caches CSV dataset records with standardized lowercased keys."""
    file_path = locate_csv_file(filename)
    if not file_path:
        return []

    try:
        mtime = file_path.stat().st_mtime
        cache_entry = _DATASET_CACHE.get(filename)
        
        if cache_entry and cache_entry["mtime"] == mtime:
            return cache_entry["data"]

        df = pd.read_csv(file_path)
        df.columns = df.columns.str.strip().str.lower()
        df = df.fillna("")
        records = df.to_dict(orient="records")

        _DATASET_CACHE[filename] = {"mtime": mtime, "data": records}
        return records
    except Exception as e:
        print(f"[CSV WARNING] Failed reading {filename}: {e}")
        return []


def extract_customer_name(cust: dict, app: dict = None) -> str:
    """Robust extractor matching name_1, short_name, or full_name from customer data."""
    if not cust:
        cust = {}
    if not app:
        app = {}

    name = (
        cust.get("name_1") or
        cust.get("short_name") or
        cust.get("full_name") or
        cust.get("customer_name") or
        cust.get("name") or
        app.get("full_name") or
        app.get("name") or
        ""
    )
    return str(name).strip() or "Applicant"


def detect_currency_symbol(val: Any) -> str:
    """Extract currency symbol if explicitly present, defaulting to '₹' (INR)."""
    val_str = str(val)
    if "$" in val_str or "USD" in val_str.upper():
        return "$"
    if "£" in val_str or "GBP" in val_str.upper():
        return "£"
    if "€" in val_str or "EUR" in val_str.upper():
        return "€"
    return "₹"


def clean_currency(val) -> float:
    if isinstance(val, (int, float)):
        return float(val)
    val_str = str(val).replace("$", "").replace("₹", "").replace("£", "").replace("€", "").replace(",", "").strip()
    try:
        return float(val_str)
    except ValueError:
        return 0.0


def format_currency_str(val, symbol: str = "₹") -> str:
    num = clean_currency(val)
    if symbol == "₹":
        return f"₹{num:,.2f}"
    elif symbol == "£":
        return f"£{num:,.2f}"
    elif symbol == "€":
        return f"€{num:,.2f}"
    return f"${num:,.2f}"


def evaluate_app_rules(app: dict, cust: dict, loans: list) -> dict:
    """Deterministic rule engine for decision, risk level, and missing document detection."""
    credit_score = int(clean_currency(app.get("credit_score") or cust.get("credit_score") or 650))
    kyc_status = str(cust.get("kyc_status") or app.get("kyc_status") or "PENDING").strip().upper()
    income = clean_currency(cust.get("monthly_income") or cust.get("income") or app.get("monthly_income") or 0)
    existing_emi = clean_currency(app.get("existing_emi") or app.get("monthly_debts") or cust.get("existing_emi") or 0)
    dti_ratio = round(((existing_emi / income) * 100), 2) if income > 0 else 0.0
    max_dpd = max([int(clean_currency(l.get("days_past_due") or l.get("dpd") or 0)) for l in loans], default=0)

    risks = []
    missing = []

    if kyc_status not in ["VERIFIED", "VALID", "COMPLETE"]:
        missing.append("Updated Government ID / KYC (Know Your Customer) Renewal Documents")

    if credit_score < 600 or max_dpd > 30 or dti_ratio > 50.0:
        decision = "REJECT"
        risk_level = "HIGH"
        if credit_score < 600:
            risks.append(f"Credit score ({credit_score}) is below minimum threshold of 600")
        if max_dpd > 30:
            risks.append(f"Delinquency history: {max_dpd} DPD (Days Past Due)")
        if dti_ratio > 50.0:
            risks.append(f"DTI (Debt-to-Income) ratio ({dti_ratio:.1f}%) exceeds 50% limit")
    elif credit_score < 700 or dti_ratio > 43.0 or max_dpd > 0 or missing:
        decision = "REFER"
        risk_level = "MEDIUM" if credit_score >= 650 else "HIGH"
        if credit_score < 700:
            risks.append(f"Moderate credit score ({credit_score}) requires officer review")
        if dti_ratio > 43.0:
            risks.append(f"Elevated DTI (Debt-to-Income) ratio ({dti_ratio:.1f}%)")
        if max_dpd > 0:
            risks.append(f"Minor payment delay history ({max_dpd} DPD)")
    else:
        decision = "APPROVE"
        risk_level = "LOW"

    if not risks:
        risks.append("No critical credit risk factors identified")
    if not missing:
        missing.append("None")

    needs_review = decision == "REFER" or risk_level == "HIGH" or (len(missing) > 0 and missing[0] != "None")

    return {
        "decision": decision,
        "risk_level": risk_level,
        "needs_review": needs_review,
        "risks": risks,
        "missing": missing,
        "dti_ratio": dti_ratio,
        "credit_score": credit_score,
        "kyc_status": kyc_status
    }


def get_groq_client() -> Optional[Groq]:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key or api_key.startswith("gsk_your_actual"):
        return None
    return Groq(api_key=api_key.strip())


# ------------------------------------------------------------------
# Request & Response Schemas
# ------------------------------------------------------------------
class EvaluateRequest(BaseModel):
    application_id: str


class AIRecommendationResult(BaseModel):
    recommendation: str = Field(..., description="APPROVE, REFER, or REJECT")
    risk_reasons: List[str]
    missing_information: List[str]
    explanation: str
    recommended_action: str


class EvaluationResponseSchema(BaseModel):
    application_id: str
    customer_id: str
    full_name: str
    customer_name: str
    income: float
    income_formatted: str
    monthly_income: float
    monthly_income_formatted: str
    employment_status: str
    employment: str
    kyc_status: str
    requested_amount: float
    requested_amount_formatted: str
    tenure_months: int
    tenure: int
    credit_score: int
    existing_emi: float
    existing_emi_formatted: str
    purpose: str
    loan_purpose: str
    total_outstanding: float
    total_outstanding_formatted: str
    max_days_past_due: int
    max_dpd: int
    active_loans_count: int
    active_loans: int
    approved_limit: float
    approved_limit_formatted: str
    utilized_limit: float
    utilized_limit_formatted: str
    available_limit: float
    available_limit_formatted: str
    collateral_type: str
    collateral_value: float
    collateral_value_formatted: str
    recommendation: str
    explanation: str
    summary: str
    rationale: str
    risk_reasons: List[str]
    missing_information: List[str]
    recommended_action: str

    customer_information: Dict[str, Any]
    customer: Dict[str, Any]
    application: Dict[str, Any]
    application_details: Dict[str, Any]
    existing_loans: Dict[str, Any]
    existing_loans_overview: Dict[str, Any]
    limits_and_collateral: Dict[str, Any]
    limits: Dict[str, Any]
    ai_result: Dict[str, Any]
    ai_recommendation: Dict[str, Any]


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------
@router.get("/applications")
async def get_applications(
    search: Optional[str] = Query(None, description="Search term across name, ID, credit score"),
    decision: Optional[str] = Query(None, description="Filter by decision: ALL, APPROVE, REFER, REJECT"),
    risk_level: Optional[str] = Query(None, description="Filter by risk level: ALL, LOW, MEDIUM, HIGH"),
    kyc_status: Optional[str] = Query(None, description="Filter by KYC status: ALL, VERIFIED, PENDING, EXPIRED"),
    purpose: Optional[str] = Query(None, description="Filter by loan purpose"),
    credit_score_range: Optional[str] = Query(None, description="Credit score range: <600, 600-699, 700-749, 750+"),
    loan_amount_range: Optional[str] = Query(None, description="Amount range: <100000, 100000-500000, >500000"),
    tenure_range: Optional[str] = Query(None, description="Tenure range: <12, 12-36, >36"),
    current_user: User = Depends(require_roles(["LOAN OFFICER", "LOAN_OFFICER", "ADMIN"]))
):
    apps_data = load_dataset("loan_applications.csv")
    cust_data = load_dataset("customers.csv")
    loans_data = load_dataset("loans.csv")

    if not apps_data:
        raise HTTPException(status_code=500, detail="loan_applications.csv dataset file not found.")

    cust_map = {str(c.get("customer_id", "")).strip().upper(): c for c in cust_data}

    loans_map = {}
    for l in loans_data:
        cid = str(l.get("customer_id", "")).strip().upper()
        loans_map.setdefault(cid, []).append(l)

    all_evaluated = []
    metrics = {
        "total": 0,
        "high_risk": 0,
        "needs_review": 0,
        "approve": 0,
        "refer": 0,
        "reject": 0
    }

    for app in apps_data:
        cust_id = str(app.get("customer_id", "")).strip().upper()
        cust = cust_map.get(cust_id, {})
        c_loans = loans_map.get(cust_id, [])

        app_id = str(app.get("application_id", "")).strip()
        
        # FIX: Extract actual customer name using name_1 / short_name
        full_name = extract_customer_name(cust, app)
        
        credit_score = int(clean_currency(app.get("credit_score") or cust.get("credit_score") or 0))
        
        raw_req = app.get("requested_amount", 0)
        curr_symbol = detect_currency_symbol(raw_req)
        requested_amount = clean_currency(raw_req)
        
        kyc = str(cust.get("kyc_status") or app.get("kyc_status") or "PENDING").strip().upper()
        loan_purpose = str(app.get("purpose") or app.get("loan_purpose") or "Personal Loan").strip()
        tenure = int(clean_currency(app.get("tenure") or app.get("tenure_months") or 12))

        rule_eval = evaluate_app_rules(app, cust, c_loans)
        app_decision = app.get("decision_label") or rule_eval["decision"]
        app_risk = rule_eval["risk_level"]
        app_needs_review = rule_eval["needs_review"]

        metrics["total"] += 1
        if app_risk == "HIGH":
            metrics["high_risk"] += 1
        if app_needs_review:
            metrics["needs_review"] += 1
        if app_decision == "APPROVE":
            metrics["approve"] += 1
        elif app_decision == "REFER":
            metrics["refer"] += 1
        elif app_decision == "REJECT":
            metrics["reject"] += 1

        record = {
            "application_id": app_id,
            "customer_id": cust_id,
            "full_name": full_name,
            "requested_amount": requested_amount,
            "requested_amount_formatted": format_currency_str(requested_amount, symbol=curr_symbol),
            "currency": curr_symbol,
            "credit_score": credit_score,
            "kyc_status": kyc,
            "purpose": loan_purpose,
            "loan_purpose": loan_purpose,
            "tenure_months": tenure,
            "decision": app_decision,
            "risk_level": app_risk,
            "needs_review": app_needs_review,
            "missing_information": rule_eval["missing"]
        }

        # Apply Filters
        if search and search.strip():
            q = search.lower().strip()
            if not (q in app_id.lower() or q in full_name.lower() or q in cust_id.lower() or q in str(credit_score)):
                continue

        if decision and decision.upper() != "ALL" and app_decision != decision.upper():
            continue

        if risk_level and risk_level.upper() != "ALL" and app_risk != risk_level.upper():
            continue

        if kyc_status and kyc_status.upper() != "ALL" and kyc not in kyc_status.upper():
            continue

        if purpose and purpose.upper() != "ALL" and purpose.lower() not in loan_purpose.lower():
            continue

        all_evaluated.append(record)

    return {
        "summary_metrics": metrics,
        "applications": all_evaluated
    }


@router.post("/evaluate", response_model=EvaluationResponseSchema)
@router.post("/evaluate/{application_id}", response_model=EvaluationResponseSchema)
async def evaluate_loan(
    req: Optional[EvaluateRequest] = None, 
    application_id: Optional[str] = None,
    current_user: User = Depends(require_roles(["LOAN OFFICER", "LOAN_OFFICER", "ADMIN"]))
):
    target_id = (application_id or (req.application_id if req else "")).strip().upper()
    if not target_id:
        raise HTTPException(status_code=400, detail="Application ID is required.")

    apps_data = load_dataset("loan_applications.csv")
    custs_data = load_dataset("customers.csv")
    loans_data = load_dataset("loans.csv")
    limits_data = load_dataset("limits_collateral.csv")

    app = next((a for a in apps_data if str(a.get("application_id", "")).strip().upper() == target_id), None)
    if not app:
        raise HTTPException(status_code=404, detail=f"Application ID '{target_id}' not found.")

    cust_id = str(app.get("customer_id", "")).strip().upper()
    cust = next((c for c in custs_data if str(c.get("customer_id", "")).strip().upper() == cust_id), {})
    customer_loans = [l for l in loans_data if str(l.get("customer_id", "")).strip().upper() == cust_id]
    limit = next((lm for lm in limits_data if str(lm.get("customer_id", "")).strip().upper() == cust_id), {})

    raw_amount = app.get("requested_amount", 0)
    symbol = detect_currency_symbol(raw_amount)

    # FIX: Correct column extractions from customers.csv, loans.csv, and limits_collateral.csv
    full_name = extract_customer_name(cust, app)
    income = clean_currency(cust.get("monthly_income") or cust.get("income") or 0)
    employment = str(cust.get("employment_type") or cust.get("employment_status") or cust.get("employment") or "Employed").strip()
    kyc_status = str(cust.get("kyc_status") or app.get("kyc_status") or "VERIFIED").strip().upper()

    requested_amount = clean_currency(raw_amount)
    tenure_months = int(clean_currency(app.get("tenure_months") or app.get("tenure") or 12))
    credit_score = int(clean_currency(app.get("credit_score") or cust.get("credit_score") or 650))
    existing_emi = clean_currency(app.get("existing_emi") or app.get("monthly_debts") or 0)
    purpose = str(app.get("purpose") or app.get("loan_purpose") or "Personal Loan").strip()

    # FIX: Check "outstanding" from loans.csv
    total_outstanding = sum([clean_currency(l.get("outstanding") or l.get("outstanding_balance") or l.get("amount") or 0) for l in customer_loans])
    max_dpd = max([int(clean_currency(l.get("days_past_due") or l.get("dpd") or 0)) for l in customer_loans], default=0)

    # FIX: Check "approved_limit" and "utilized" from limits_collateral.csv
    approved_limit = clean_currency(limit.get("approved_limit") or limit.get("limit") or 0)
    utilized_limit = clean_currency(limit.get("utilized") or limit.get("utilized_limit") or total_outstanding)
    available_limit = clean_currency(limit.get("available") or max(0.0, approved_limit - utilized_limit))
    collateral_type = str(limit.get("collateral_type") or limit.get("collateral") or "None").strip()
    collateral_value = clean_currency(limit.get("collateral_value") or 0)

    dti_ratio = round(((existing_emi / income) * 100), 2) if income > 0 else 0.0

    rule_eval = evaluate_app_rules(app, cust, customer_loans)

    groq_client = get_groq_client()
    ai_result = None

    if groq_client:
        prompt = f"""
        You are a Bank Credit Risk Underwriter. Explain the pre-calculated decision for this loan application.

        DETERMINISTIC RULE RESULTS (DO NOT OVERRIDE):
        - Calculated Decision: {rule_eval['decision']}
        - Identified Risk Reasons: {rule_eval['risks']}
        - Missing Required Information: {rule_eval['missing']}

        CUSTOMER INFORMATION:
        - Customer ID: {cust_id}
        - Full Name: {full_name}
        - Monthly Income: {format_currency_str(income, symbol)}
        - Employment Status: {employment}
        - KYC Status: {kyc_status}

        APPLICATION DETAILS:
        - Application ID: {target_id}
        - Requested Amount: {format_currency_str(requested_amount, symbol)}
        - Tenure: {tenure_months} months
        - Credit Score: {credit_score}
        - Existing EMI: {format_currency_str(existing_emi, symbol)}
        - Calculated DTI Ratio: {dti_ratio}%
        - Purpose: {purpose}

        EXISTING LOANS:
        - Total Outstanding Balance: {format_currency_str(total_outstanding, symbol)}
        - Max DPD: {max_dpd} days
        - Active Loans Count: {len(customer_loans)}

        IMPORTANT ACRONYM RULE:
        Whenever introducing an abbreviation or acronym for the FIRST time, explain its full meaning in brackets immediately.
        Examples: KYC (Know Your Customer), EMI (Equated Monthly Instalment), DTI (Debt-to-Income), DPD (Days Past Due).

        Return ONLY strict JSON with these keys:
        {{
          "recommendation": "{rule_eval['decision']}",
          "risk_reasons": {json.dumps(rule_eval['risks'])},
          "missing_information": {json.dumps(rule_eval['missing'])},
          "explanation": "A concise 2-3 sentence plain language explanation of why this application was {rule_eval['decision']}.",
          "recommended_action": "Clear, single actionable next step for the loan officer."
        }}
        """
        try:
            response = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": "You are a professional banking credit underwriter. Output only strict JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1
            )
            raw_res = json.loads(response.choices[0].message.content)
            ai_result = AIRecommendationResult(**raw_res)
        except Exception as e:
            print(f"[AI UNDERWRITER WARNING] Groq call failed: {e}")

    if not ai_result:
        rec = rule_eval["decision"]
        if rec == "REFER":
            rec_action = "Review pending KYC (Know Your Customer) documents and re-verify DTI (Debt-to-Income) ratio with applicant."
        elif rec == "REJECT":
            rec_action = "Application does not meet credit benchmarks. Send formal adverse action notice to customer."
        else:
            rec_action = "Proceed with standard loan agreement issuance and disbursement authorization."

        exp = (
            f"The application for {full_name} was evaluated as {rec}. The customer has a credit score of {credit_score} "
            f"and a calculated DTI (Debt-to-Income) ratio of {dti_ratio:.1f}%. "
            + ("Elevated risk factors or pending documents require manual underwriter approval." if rec == "REFER"
               else "Financial profile meets standard credit policy benchmarks." if rec == "APPROVE"
               else "Financial risk indicators fall outside approved lending criteria.")
        )
        ai_result = AIRecommendationResult(
            recommendation=rec,
            risk_reasons=rule_eval["risks"],
            missing_information=rule_eval["missing"],
            explanation=exp,
            recommended_action=rec_action
        )

    cust_dict = {
        "customer_id": cust_id,
        "full_name": full_name,
        "customer_name": full_name,
        "income": income,
        "income_formatted": format_currency_str(income, symbol),
        "monthly_income": income,
        "monthly_income_formatted": format_currency_str(income, symbol),
        "employment_status": employment,
        "employment": employment,
        "kyc_status": kyc_status
    }

    app_dict = {
        "application_id": target_id,
        "requested_amount": requested_amount,
        "requested_amount_formatted": format_currency_str(requested_amount, symbol),
        "tenure_months": tenure_months,
        "tenure": tenure_months,
        "credit_score": credit_score,
        "existing_emi": existing_emi,
        "existing_emi_formatted": format_currency_str(existing_emi, symbol),
        "purpose": purpose,
        "loan_purpose": purpose
    }

    loans_dict = {
        "total_outstanding": total_outstanding,
        "total_outstanding_formatted": format_currency_str(total_outstanding, symbol),
        "max_days_past_due": max_dpd,
        "max_dpd": max_dpd,
        "active_loans_count": len(customer_loans),
        "active_loans": len(customer_loans)
    }

    limits_dict = {
        "approved_limit": approved_limit,
        "approved_limit_formatted": format_currency_str(approved_limit, symbol),
        "utilized_limit": utilized_limit,
        "utilized_limit_formatted": format_currency_str(utilized_limit, symbol),
        "available_limit": available_limit,
        "available_limit_formatted": format_currency_str(available_limit, symbol),
        "collateral_type": collateral_type,
        "collateral_value": collateral_value,
        "collateral_value_formatted": format_currency_str(collateral_value, symbol)
    }

    ai_dict = ai_result.model_dump() if hasattr(ai_result, "model_dump") else ai_result.dict()

    return {
        "application_id": target_id,
        "customer_id": cust_id,
        "full_name": full_name,
        "customer_name": full_name,
        "income": income,
        "income_formatted": format_currency_str(income, symbol),
        "monthly_income": income,
        "monthly_income_formatted": format_currency_str(income, symbol),
        "employment_status": employment,
        "employment": employment,
        "kyc_status": kyc_status,
        "requested_amount": requested_amount,
        "requested_amount_formatted": format_currency_str(requested_amount, symbol),
        "tenure_months": tenure_months,
        "tenure": tenure_months,
        "credit_score": credit_score,
        "existing_emi": existing_emi,
        "existing_emi_formatted": format_currency_str(existing_emi, symbol),
        "purpose": purpose,
        "loan_purpose": purpose,
        "total_outstanding": total_outstanding,
        "total_outstanding_formatted": format_currency_str(total_outstanding, symbol),
        "max_days_past_due": max_dpd,
        "max_dpd": max_dpd,
        "active_loans_count": len(customer_loans),
        "active_loans": len(customer_loans),
        "approved_limit": approved_limit,
        "approved_limit_formatted": format_currency_str(approved_limit, symbol),
        "utilized_limit": utilized_limit,
        "utilized_limit_formatted": format_currency_str(utilized_limit, symbol),
        "available_limit": available_limit,
        "available_limit_formatted": format_currency_str(available_limit, symbol),
        "collateral_type": collateral_type,
        "collateral_value": collateral_value,
        "collateral_value_formatted": format_currency_str(collateral_value, symbol),
        "recommendation": ai_result.recommendation,
        "explanation": ai_result.explanation,
        "summary": ai_result.explanation,
        "rationale": ai_result.explanation,
        "risk_reasons": ai_result.risk_reasons,
        "missing_information": ai_result.missing_information,
        "recommended_action": ai_result.recommended_action,

        "customer_information": cust_dict,
        "customer": cust_dict,
        "application": app_dict,
        "application_details": app_dict,
        "existing_loans": loans_dict,
        "existing_loans_overview": loans_dict,
        "limits_and_collateral": limits_dict,
        "limits": limits_dict,
        "ai_result": ai_dict,
        "ai_recommendation": ai_dict
    }