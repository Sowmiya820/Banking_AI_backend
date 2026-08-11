import os
import json
from pathlib import Path
from typing import List, Optional, Dict, Any
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.audit import log_audit_event
from app.core.dependencies import require_roles

# Safe User model import fallback
try:
    from app.db.models.models import User
except ImportError:
    User = dict  # Fallback type hint if User model path differs

# Safe Groq SDK import check
try:
    from groq import Groq
    GROQ_SDK_AVAILABLE = True
except ImportError:
    GROQ_SDK_AVAILABLE = False

router = APIRouter(prefix="/letter-writer", tags=["Module A4: Bank Letter Writer"])

# ------------------------------------------------------------------
# CSV DATASET LOADER (Identical to Module A1)
# ------------------------------------------------------------------
CURRENT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = CURRENT_DIR.parent.parent.parent.parent

DATA_SEARCH_DIRS = [
    BACKEND_DIR / "data",
    BACKEND_DIR / "app" / "data",
    Path("data"),
    Path("backend/data"),
]

_DATASET_CACHE: Dict[str, Dict[str, Any]] = {}


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
    return str(name).strip() or "Valued Customer"


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


# ------------------------------------------------------------------
# SCHEMAS
# ------------------------------------------------------------------
class LetterRequest(BaseModel):
    application_id: Optional[str] = Field(default=None, json_schema_extra={"example": "APP001"})
    customer_id: str = Field(..., json_schema_extra={"example": "CUST001"})
    customer_name: Optional[str] = Field(default="Valued Customer", json_schema_extra={"example": "Arun"})
    letter_type: str = Field(default="LOAN_DECISION", json_schema_extra={"example": "LOAN_DECISION"})  # LOAN_DECISION, KYC_REQUEST, LOAN_LIMIT
    loan_type: Optional[str] = Field(default="Vehicle Loan", json_schema_extra={"example": "Vehicle Loan"})
    decision: Optional[str] = Field(default="REFER", json_schema_extra={"example": "REFER"})  # APPROVED, REJECTED, REFER
    reason: Optional[str] = Field(default="KYC information needs updating", json_schema_extra={"example": "KYC information needs updating"})
    missing_info: Optional[str] = Field(default="Updated KYC information", json_schema_extra={"example": "Updated KYC information"})
    current_limit: Optional[str] = Field(default=None, json_schema_extra={"example": "₹5,000.00"})
    new_limit: Optional[str] = Field(default=None, json_schema_extra={"example": "₹10,000.00"})


class FactItem(BaseModel):
    label: str
    detail: str
    is_used: bool = True


class LetterResponse(BaseModel):
    status: str = "success"
    subject: str
    letter_text: str
    facts_used: List[FactItem]
    unsupported_facts: List[str] = []
    evaluator: str = "Groq Plain-Language Engine"


class VerifiedFactsResponse(BaseModel):
    application_id: Optional[str]
    customer_id: str
    customer_name: str
    loan_type: Optional[str]
    decision: Optional[str]
    reason: Optional[str]
    missing_info: Optional[str]
    current_limit: Optional[str]
    new_limit: Optional[str]
    kyc_status: Optional[str]


# ------------------------------------------------------------------
# HELPER: CSV FACT RETRIEVAL (Matches Module A1 Data Structure)
# ------------------------------------------------------------------
def fetch_verified_facts_by_app(application_id: str) -> dict:
    """Fetch authoritative verified facts from CSV datasets (matching Module A1 source)."""
    clean_app_id = application_id.strip().upper()

    apps_data = load_dataset("loan_applications.csv")
    custs_data = load_dataset("customers.csv")
    limits_data = load_dataset("limits_collateral.csv")

    if not apps_data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="loan_applications.csv dataset file not found."
        )

    app = next((a for a in apps_data if str(a.get("application_id", "")).strip().upper() == clean_app_id), None)
    if not app:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unable to find application ID '{clean_app_id}'."
        )

    cust_id = str(app.get("customer_id", "")).strip().upper()
    cust = next((c for c in custs_data if str(c.get("customer_id", "")).strip().upper() == cust_id), {})
    limit = next((lm for lm in limits_data if str(lm.get("customer_id", "")).strip().upper() == cust_id), {})

    customer_name = extract_customer_name(cust, app)
    loan_type = str(app.get("purpose") or app.get("loan_purpose") or app.get("loan_type") or "Personal Loan").strip()
    decision = str(app.get("decision_label") or app.get("decision") or "REFER").strip().upper()
    
    reason = str(
        app.get("decision_rationale") or 
        app.get("reason") or 
        "Underwriting review required"
    ).strip()

    missing_info = str(app.get("missing_information") or app.get("missing_info") or "").strip() or None

    kyc_status = str(cust.get("kyc_status") or app.get("kyc_status") or "PENDING").strip().upper()

    curr_limit_val = limit.get("available_limit") or limit.get("available") or limit.get("utilized")
    appr_limit_val = limit.get("approved_limit") or limit.get("limit")

    formatted_curr_limit = format_currency_str(curr_limit_val) if curr_limit_val != "" and curr_limit_val is not None else None
    formatted_appr_limit = format_currency_str(appr_limit_val) if appr_limit_val != "" and appr_limit_val is not None else None

    return {
        "application_id": clean_app_id,
        "customer_id": cust_id,
        "customer_name": customer_name,
        "loan_type": loan_type,
        "decision": decision,
        "reason": reason,
        "missing_info": missing_info,
        "current_limit": formatted_curr_limit,
        "new_limit": formatted_appr_limit,
        "kyc_status": kyc_status
    }


# ------------------------------------------------------------------
# ROUTE ENDPOINTS
# ------------------------------------------------------------------
@router.get("/facts/{application_id}", response_model=VerifiedFactsResponse)
async def get_verified_application_facts(
    application_id: str,
    current_user: User = Depends(require_roles(["RELATIONSHIP MANAGER", "RELATIONSHIP_MANAGER", "LOAN OFFICER", "LOAN_OFFICER", "ADMIN"]))
):
    """
    Retrieves authoritative verified application, customer, and limit facts 
    directly from CSV datasets (matching Module A1) for letter generation.
    """
    facts = fetch_verified_facts_by_app(application_id)
    return VerifiedFactsResponse(**facts)


@router.post("/generate", response_model=LetterResponse)
async def generate_bank_letter(
    payload: LetterRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(["RELATIONSHIP MANAGER", "RELATIONSHIP_MANAGER", "LOAN OFFICER", "LOAN_OFFICER", "ADMIN"]))
):
    """
    Module A4 Plain-Language Bank Letter Writer:
    1. If application_id is provided, fetches authoritative facts from CSV datasets (matching Module A1).
    2. Enforces strict zero-hallucination LLM grounding and Acronym Rule expansions.
    3. Provides deterministic fallback template generation if LLM is offline.
    4. Computes factual audit breakdown (Facts Used vs. Unsupported Facts).
    5. Logs the communication generation to the DB audit trail.
    """
    customer_id = payload.customer_id
    customer_name = payload.customer_name or "Valued Customer"
    loan_type = payload.loan_type or "Personal Loan"
    decision = (payload.decision or "REFER").upper()
    reason = payload.reason or "Information required"
    missing_info = payload.missing_info
    current_limit = payload.current_limit
    new_limit = payload.new_limit

    # Fetch CSV facts if application_id is provided
    if payload.application_id:
        try:
            csv_facts = fetch_verified_facts_by_app(payload.application_id)
            customer_id = csv_facts["customer_id"]
            customer_name = csv_facts["customer_name"]
            loan_type = csv_facts["loan_type"] or loan_type
            decision = (csv_facts["decision"] or decision).upper()
            reason = csv_facts["reason"] or reason
            missing_info = csv_facts["missing_info"] or missing_info
            current_limit = csv_facts["current_limit"] or current_limit
            new_limit = csv_facts["new_limit"] or new_limit
        except HTTPException:
            raise
        except Exception as e:
            print(f"⚠️ [CSV Fact Retrieval Warning] Falling back to payload facts: {e}")

    # Build audit trace
    facts_trace: List[FactItem] = [
        FactItem(label="Customer Name", detail=customer_name, is_used=True),
        FactItem(label="Customer ID", detail=customer_id, is_used=True),
    ]

    letter_type = payload.letter_type.upper()
    if letter_type == "LOAN_DECISION":
        facts_trace.append(FactItem(label="Loan Type", detail=loan_type, is_used=True))
        facts_trace.append(FactItem(label="Decision", detail=decision, is_used=True))
        facts_trace.append(FactItem(label="Decision Reason", detail=reason, is_used=True))
        if missing_info:
            facts_trace.append(FactItem(label="Missing Information", detail=missing_info, is_used=True))
    elif letter_type == "KYC_REQUEST":
        facts_trace.append(FactItem(label="KYC Status / Requirement", detail=reason, is_used=True))
        if missing_info:
            facts_trace.append(FactItem(label="Missing Documents", detail=missing_info, is_used=True))
    elif letter_type == "LOAN_LIMIT":
        if current_limit:
            facts_trace.append(FactItem(label="Current Limit", detail=current_limit, is_used=True))
        if new_limit:
            facts_trace.append(FactItem(label="Approved/New Limit", detail=new_limit, is_used=True))
        facts_trace.append(FactItem(label="Limit Reason", detail=reason, is_used=True))

    subject = ""
    letter_text = ""
    unsupported_facts: List[str] = []
    evaluator_used = "Rule Engine (Fallback)"
    groq_api_key = os.getenv("GROQ_API_KEY")

    # LLM Generation Strategy
    if groq_api_key and GROQ_SDK_AVAILABLE:
        try:
            client = Groq(api_key=groq_api_key)

            prompt = f"""
You are an expert plain-language banking customer communication generator.
Draft a simple, professional, empathetic bank letter using ONLY the verified facts below.

VERIFIED BANKING FACTS:
- Letter Type: {letter_type}
- Customer Name: {customer_name}
- Customer ID: {customer_id}
- Loan Type: {loan_type}
- Decision Outcome: {decision}
- Underwriting Reason: {reason}
- Action / Missing Info Required: {missing_info or 'None'}
- Current Limit: {current_limit or 'N/A'}
- New / Approved Limit: {new_limit or 'N/A'}

STRICT GROUNDING RULES:
1. Use ONLY the supplied verified facts. Do NOT invent or infer credit scores, interest rates, penalties, fake dates, loan amounts, or unsupplied reasons.
2. Do NOT change the supplied decision.
3. ACRONYM RULE: The FIRST time an acronym or abbreviation is used (e.g. KYC, EMI, DTI, APR), write out its full definition in brackets immediately after.
   Examples: "KYC (Know Your Customer)", "EMI (Equated Monthly Instalment)", "DTI (Debt-to-Income)", "APR (Annual Percentage Rate)".
4. Use simple, empathetic, customer-friendly language without banking jargon.

Respond ONLY in valid, strict JSON matching this structure:
{{
    "subject": "Clear subject line",
    "letter_body": "Dear {customer_name},\\n\\n[Short paragraph 1]\\n\\n[Short paragraph 2]\\n\\nSincerely,\\nBank Application Review Team",
    "facts_used": ["Customer Name", "Loan Type", "Decision", "Decision Reason", "Missing Information"],
    "unsupported_facts": []
}}
"""
            completion = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.2,
                max_tokens=700
            )

            llm_res = json.loads(completion.choices[0].message.content)
            subject = llm_res.get("subject", "")
            letter_text = llm_res.get("letter_body", "")
            unsupported_facts = llm_res.get("unsupported_facts", [])

            if letter_text:
                evaluator_used = "Groq LLM Engine (llama-3.3-70b-versatile)"

        except Exception as e:
            print(f"⚠️ [Letter Writer LLM Fallback] Error: {e}")

    # Fallback Rule Engine
    if not letter_text:
        if letter_type == "KYC_REQUEST":
            subject = "Update Required for Your Bank Account Documentation"
            letter_text = (
                f"Dear {customer_name},\n\n"
                f"Thank you for banking with us.\n\n"
                f"To keep your account active and up to date, we require updated KYC (Know Your Customer) information.\n\n"
                f"Required information: {missing_info or 'Updated proof of identity or address'}.\n\n"
                f"Please submit these documents at your earliest convenience so we can complete our review.\n\n"
                f"Sincerely,\nBank Customer Support Team"
            )
        elif letter_type == "LOAN_LIMIT":
            subject = f"Information Regarding Your {loan_type} Limit"
            limit_details = f"Your current limit is {current_limit}." if current_limit else ""
            if new_limit:
                limit_details += f" Your updated limit is {new_limit}."
            letter_text = (
                f"Dear {customer_name},\n\n"
                f"We are writing to provide an update regarding your {loan_type} limit.\n\n"
                f"{limit_details}\n\n"
                f"Reason: {reason}.\n\n"
                f"Thank you for choosing us for your banking needs.\n\n"
                f"Sincerely,\nBank Credit Operations Team"
            )
        else:  # LOAN_DECISION
            if decision == "REFER":
                subject = f"Update Required for Your {loan_type} Application"
                letter_text = (
                    f"Dear {customer_name},\n\n"
                    f"Thank you for your {loan_type} application.\n\n"
                    f"We have reviewed your application and require additional information before we can complete the process.\n\n"
                    f"Your KYC (Know Your Customer) information needs to be updated. Please provide: {missing_info or 'the requested documentation'}.\n\n"
                    f"Thank you for your cooperation.\n\n"
                    f"Sincerely,\nBank Application Review Team"
                )
            elif decision == "APPROVED" or decision == "APPROVE":
                subject = f"Approval Notice for Your {loan_type} Application"
                letter_text = (
                    f"Dear {customer_name},\n\n"
                    f"We are pleased to inform you that your application for a {loan_type} has been approved.\n\n"
                    f"Review summary: {reason}.\n\n"
                    f"Our team will contact you shortly regarding the next steps.\n\n"
                    f"Sincerely,\nBank Application Review Team"
                )
            else:  # REJECTED / REJECT
                subject = f"Update Regarding Your {loan_type} Application"
                letter_text = (
                    f"Dear {customer_name},\n\n"
                    f"Thank you for applying for a {loan_type} with us.\n\n"
                    f"After careful review, we regret to inform you that we are unable to approve your application at this time.\n\n"
                    f"Reason for decision: {reason}.\n\n"
                    f"Thank you for your time and interest in our services.\n\n"
                    f"Sincerely,\nBank Application Review Team"
                )

    # Audit Trail Logging
    try:
        user_id = getattr(current_user, "user_id", getattr(current_user, "id", "SYSTEM"))
        await log_audit_event(
            db=db,
            user_id=user_id,
            action="GENERATE_BANK_LETTER",
            endpoint="/api/v1/letter-writer/generate",
            details=f"Generated {letter_type} letter for Customer ID: {customer_id} ({evaluator_used})"
        )
    except Exception as audit_err:
        print(f"⚠️ [AUDIT LOG WARNING] Failed to record audit log: {audit_err}")

    return LetterResponse(
        status="success",
        subject=subject,
        letter_text=letter_text,
        facts_used=facts_trace,
        unsupported_facts=unsupported_facts,
        evaluator=evaluator_used
    )