import os
import json
import traceback
from pathlib import Path
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
import pandas as pd
from groq import Groq
from dotenv import load_dotenv

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
    file_path = locate_csv_file(filename)
    if not file_path:
        return []
    try:
        df = pd.read_csv(file_path)
        df.columns = df.columns.str.strip().str.lower()
        df = df.fillna("")
        return df.to_dict(orient="records")
    except Exception as e:
        print(f"[CSV WARNING] Failed reading {filename}: {e}")
        return []


def clean_currency(val) -> float:
    if isinstance(val, (int, float)):
        return float(val)
    val_str = str(val).replace("$", "").replace("₹", "").replace(",", "").strip()
    try:
        return float(val_str)
    except ValueError:
        return 0.0


def format_currency_str(val) -> str:
    num = clean_currency(val)
    return f"${num:,.2f}"


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


class EvaluationResponseSchema(BaseModel):
    # Flat Keys
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

    # Nested Section Aliases
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
async def get_applications(search: Optional[str] = Query(None, description="Search term")):
    apps_data = load_dataset("loan_applications.csv")
    cust_data = load_dataset("customers.csv")

    if not apps_data:
        raise HTTPException(status_code=500, detail="loan_applications.csv dataset file not found.")

    cust_map = {str(c.get("customer_id", "")).strip().upper(): c for c in cust_data}

    results = []
    for app in apps_data:
        cust_id = str(app.get("customer_id", "")).strip().upper()
        cust = cust_map.get(cust_id, {})

        app_id = str(app.get("application_id", "")).strip()
        full_name = str(app.get("full_name") or cust.get("full_name") or cust.get("name") or "Applicant").strip()
        credit_score = int(clean_currency(app.get("credit_score") or cust.get("credit_score") or 0))
        requested_amount = clean_currency(app.get("requested_amount", 0))
        kyc_status = str(cust.get("kyc_status") or app.get("kyc_status") or "PENDING").strip().upper()

        if search and search.strip():
            q = search.lower().strip()
            if not (
                q in app_id.lower()
                or q in full_name.lower()
                or q in str(credit_score)
                or q in str(requested_amount)
                or q in kyc_status.lower()
            ):
                continue

        results.append({
            "application_id": app_id,
            "customer_id": cust_id,
            "full_name": full_name,
            "requested_amount": format_currency_str(requested_amount),
            "credit_score": credit_score,
            "kyc_status": kyc_status
        })

    return results


@router.post("/evaluate", response_model=EvaluationResponseSchema)
@router.post("/evaluate/{application_id}", response_model=EvaluationResponseSchema)
async def evaluate_loan(req: Optional[EvaluateRequest] = None, application_id: Optional[str] = None):
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

    income = clean_currency(cust.get("monthly_income") or cust.get("income") or app.get("monthly_income") or 0)
    employment = str(cust.get("employment_status") or cust.get("employment") or "Employed").strip()
    kyc_status = str(cust.get("kyc_status") or app.get("kyc_status") or "VERIFIED").strip().upper()
    full_name = str(cust.get("full_name") or cust.get("name") or app.get("full_name") or "Applicant").strip()

    requested_amount = clean_currency(app.get("requested_amount", 0))
    tenure_months = int(clean_currency(app.get("tenure") or app.get("tenure_months") or 12))
    credit_score = int(clean_currency(app.get("credit_score") or cust.get("credit_score") or 650))
    existing_emi = clean_currency(app.get("existing_emi") or app.get("monthly_debts") or cust.get("existing_emi") or 0)
    purpose = str(app.get("purpose") or app.get("loan_purpose") or "Personal Loan").strip()

    total_outstanding = sum([clean_currency(l.get("outstanding_balance") or l.get("amount") or 0) for l in customer_loans])
    max_dpd = max([int(clean_currency(l.get("days_past_due") or l.get("dpd") or 0)) for l in customer_loans], default=0)

    approved_limit = clean_currency(limit.get("approved_limit") or limit.get("limit") or 50000)
    utilized_limit = clean_currency(limit.get("utilized_limit") or limit.get("utilized") or total_outstanding)
    available_limit = max(0.0, approved_limit - utilized_limit)
    collateral_type = str(limit.get("collateral_type") or limit.get("collateral") or "None").strip()
    collateral_value = clean_currency(limit.get("collateral_value") or 0)

    dti_ratio = round(((existing_emi / income) * 100), 2) if income > 0 else 0.0

    groq_client = get_groq_client()
    ai_result = None

    if groq_client:
        prompt = f"""
        Analyze this loan application based on standard bank credit policy guidelines.

        CUSTOMER INFORMATION:
        - Customer ID: {cust_id}
        - Monthly Income: ${income:,.2f}
        - Employment Status: {employment}
        - KYC Status: {kyc_status}

        APPLICATION DETAILS:
        - Application ID: {target_id}
        - Requested Amount: ${requested_amount:,.2f}
        - Tenure: {tenure_months} months
        - Credit Score: {credit_score}
        - Existing EMI: ${existing_emi:,.2f}
        - Calculated DTI Ratio: {dti_ratio}%
        - Purpose: {purpose}

        EXISTING LOANS:
        - Total Outstanding Balance: ${total_outstanding:,.2f}
        - Max Days Past Due (DPD): {max_dpd} days
        - Active Loans Count: {len(customer_loans)}

        LIMITS & COLLATERAL:
        - Approved Limit: ${approved_limit:,.2f}
        - Utilized Limit: ${utilized_limit:,.2f}
        - Collateral Type: {collateral_type}
        - Collateral Value: ${collateral_value:,.2f}

        POLICY RULES:
        - APPROVE: Credit Score >= 700, DTI <= 43%, Max DPD == 0, KYC Verified.
        - REFER: Credit Score 600-699, DTI 43%-50%, Max DPD 1-30 days, or KYC Pending/Expired.
        - REJECT: Credit Score < 600, DTI > 50%, or Max DPD > 30 days.

        Return ONLY strict JSON with these keys:
        {{
          "recommendation": "APPROVE" | "REFER" | "REJECT",
          "risk_reasons": ["Specific risk bullet 1"],
          "missing_information": ["Missing doc 1" or "None"],
          "explanation": "A simple 2-3 sentence plain language explanation of why this decision was reached."
        }}
        """
        try:
            response = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": "You are a Bank Credit Risk Underwriter. Output only strict valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1
            )
            raw_res = json.loads(response.choices[0].message.content)
            ai_result = AIRecommendationResult(**raw_res)
        except Exception as e:
            print(f"[AI UNDERWRITER WARNING] Groq call failed: {e}")

    if not ai_result:
        risks = []
        missing = []
        if kyc_status not in ["VERIFIED", "COMPLETE"]:
            missing.append("Updated Government ID / KYC Renewal Documents")

        if credit_score < 600 or max_dpd > 30 or dti_ratio > 50.0:
            rec = "REJECT"
            if credit_score < 600:
                risks.append(f"Credit score ({credit_score}) is below minimum threshold of 600")
            if max_dpd > 30:
                risks.append(f"Significant delinquency history: {max_dpd} Days Past Due")
            if dti_ratio > 50.0:
                risks.append(f"Debt-to-Income ratio ({dti_ratio:.1f}%) exceeds maximum limit of 50%")
        elif credit_score < 700 or dti_ratio > 43.0 or max_dpd > 0 or missing:
            rec = "REFER"
            if credit_score < 700:
                risks.append(f"Moderate credit score ({credit_score}) requires officer review")
            if dti_ratio > 43.0:
                risks.append(f"Elevated Debt-to-Income ratio ({dti_ratio:.1f}%)")
            if max_dpd > 0:
                risks.append(f"Minor payment delay history ({max_dpd} DPD)")
        else:
            rec = "APPROVE"

        if not risks:
            risks.append("No critical credit risk factors identified")
        if not missing:
            missing.append("None")

        exp = (
            f"The application was evaluated as {rec}. The customer has a credit score of {credit_score} "
            f"and a calculated Debt-to-Income ratio of {dti_ratio:.1f}%. "
            + ("Elevated risk factors or pending documents require manual underwriter approval." if rec == "REFER"
               else "Financial profile meets standard credit policy benchmarks." if rec == "APPROVE"
               else "Financial risk indicators fall outside approved lending criteria.")
        )
        ai_result = AIRecommendationResult(
            recommendation=rec,
            risk_reasons=risks,
            missing_information=missing,
            explanation=exp
        )

    cust_dict = {
        "customer_id": cust_id,
        "full_name": full_name,
        "customer_name": full_name,
        "income": income,
        "income_formatted": format_currency_str(income),
        "monthly_income": income,
        "monthly_income_formatted": format_currency_str(income),
        "employment_status": employment,
        "employment": employment,
        "kyc_status": kyc_status
    }

    app_dict = {
        "application_id": target_id,
        "requested_amount": requested_amount,
        "requested_amount_formatted": format_currency_str(requested_amount),
        "tenure_months": tenure_months,
        "tenure": tenure_months,
        "credit_score": credit_score,
        "existing_emi": existing_emi,
        "existing_emi_formatted": format_currency_str(existing_emi),
        "purpose": purpose,
        "loan_purpose": purpose
    }

    loans_dict = {
        "total_outstanding": total_outstanding,
        "total_outstanding_formatted": format_currency_str(total_outstanding),
        "max_days_past_due": max_dpd,
        "max_dpd": max_dpd,
        "active_loans_count": len(customer_loans),
        "active_loans": len(customer_loans)
    }

    limits_dict = {
        "approved_limit": approved_limit,
        "approved_limit_formatted": format_currency_str(approved_limit),
        "utilized_limit": utilized_limit,
        "utilized_limit_formatted": format_currency_str(utilized_limit),
        "available_limit": available_limit,
        "available_limit_formatted": format_currency_str(available_limit),
        "collateral_type": collateral_type,
        "collateral_value": collateral_value,
        "collateral_value_formatted": format_currency_str(collateral_value)
    }

    ai_dict = ai_result.dict()

    return {
        "application_id": target_id,
        "customer_id": cust_id,
        "full_name": full_name,
        "customer_name": full_name,
        "income": income,
        "income_formatted": format_currency_str(income),
        "monthly_income": income,
        "monthly_income_formatted": format_currency_str(income),
        "employment_status": employment,
        "employment": employment,
        "kyc_status": kyc_status,
        "requested_amount": requested_amount,
        "requested_amount_formatted": format_currency_str(requested_amount),
        "tenure_months": tenure_months,
        "tenure": tenure_months,
        "credit_score": credit_score,
        "existing_emi": existing_emi,
        "existing_emi_formatted": format_currency_str(existing_emi),
        "purpose": purpose,
        "loan_purpose": purpose,
        "total_outstanding": total_outstanding,
        "total_outstanding_formatted": format_currency_str(total_outstanding),
        "max_days_past_due": max_dpd,
        "max_dpd": max_dpd,
        "active_loans_count": len(customer_loans),
        "active_loans": len(customer_loans),
        "approved_limit": approved_limit,
        "approved_limit_formatted": format_currency_str(approved_limit),
        "utilized_limit": utilized_limit,
        "utilized_limit_formatted": format_currency_str(utilized_limit),
        "available_limit": available_limit,
        "available_limit_formatted": format_currency_str(available_limit),
        "collateral_type": collateral_type,
        "collateral_value": collateral_value,
        "collateral_value_formatted": format_currency_str(collateral_value),
        "recommendation": ai_result.recommendation,
        "explanation": ai_result.explanation,
        "summary": ai_result.explanation,
        "rationale": ai_result.explanation,
        "risk_reasons": ai_result.risk_reasons,
        "missing_information": ai_result.missing_information,

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