from decimal import Decimal
from typing import List, Dict, Any, Tuple, Optional  # <--- Added Optional here

def evaluate_loan_application(
    customer: Dict[str, Any],
    application: Dict[str, Any],
    existing_loans: List[Dict[str, Any]],
    limits_collateral: Optional[Dict[str, Any]]
) -> Tuple[str, float, float, List[Dict[str, str]], List[str], Dict[str, Any]]:

    risk_factors: List[Dict[str, str]] = []
    missing_info: List[str] = []
    
    # 1. Base Variables Extraction
    monthly_income = float(customer.get("monthly_income") or 0.0)
    credit_score = int(customer.get("credit_score") or 0)
    kyc_status = str(customer.get("kyc_status", "PENDING")).upper()
    
    requested_amount = float(application.get("requested_amount") or 0.0)
    tenure_months = int(application.get("requested_tenure_months") or 12)
    
    # Calculate Proposed EMI assuming standard interest rate (10.5% per annum)
    monthly_rate = (10.5 / 100) / 12
    if monthly_rate > 0 and tenure_months > 0:
        proposed_emi = requested_amount * monthly_rate * ((1 + monthly_rate) ** tenure_months) / (((1 + monthly_rate) ** tenure_months) - 1)
    else:
        proposed_emi = requested_amount / tenure_months if tenure_months > 0 else 0
        
    # Total Monthly Debt Obligations
    existing_emi_sum = sum(float(l.get("monthly_emi") or 0.0) for l in existing_loans)
    total_monthly_debt = existing_emi_sum + proposed_emi
    
    # Debt-to-Income (DTI) Ratio Calculation
    calculated_dti = (total_monthly_debt / monthly_income * 100) if monthly_income > 0 else 999.0
    
    # Collateral & LTV Calculation
    collateral_val = float(limits_collateral.get("collateral_value") or 0.0) if limits_collateral else 0.0
    calculated_ltv = (requested_amount / collateral_val * 100) if collateral_val > 0 else (100.0 if requested_amount > 0 else 0.0)

    # -------------------------------------------------------------
    # DETERMINISTIC RULE EVALUATIONS
    # -------------------------------------------------------------
    is_reject = False
    is_refer = False

    # Rule 1: KYC Verification Check
    if kyc_status != "VERIFIED":
        is_reject = True
        risk_factors.append({
            "code": "KYC_NOT_VERIFIED",
            "severity": "HIGH",
            "message": f"Customer KYC status is '{kyc_status}'. Verified KYC is required for loan sanction."
        })
        missing_info.append("Updated Government ID proof and Video-KYC completion certificate.")

    # Rule 2: Credit Score Threshold Check
    if credit_score < 600:
        is_reject = True
        risk_factors.append({
            "code": "LOW_CREDIT_SCORE",
            "severity": "HIGH",
            "message": f"Credit score of {credit_score} is below the minimum threshold of 600."
        })
    elif 600 <= credit_score < 680:
        is_refer = True
        risk_factors.append({
            "code": "MODERATE_CREDIT_SCORE",
            "severity": "MEDIUM",
            "message": f"Credit score of {credit_score} is in the fair band (600-679). Requires senior risk officer sign-off."
        })

    # Rule 3: Debt-To-Income (DTI) Threshold Check
    if calculated_dti > 50.0:
        is_reject = True
        risk_factors.append({
            "code": "EXCESSIVE_DTI",
            "severity": "HIGH",
            "message": f"Calculated DTI ratio of {calculated_dti:.1f}% exceeds the maximum limit of 50.0%."
        })
    elif 40.0 < calculated_dti <= 50.0:
        is_refer = True
        risk_factors.append({
            "code": "ELEVATED_DTI",
            "severity": "MEDIUM",
            "message": f"Calculated DTI ratio of {calculated_dti:.1f}% is elevated (40.0% - 50.0%)."
        })

    # Rule 4: Default History Check
    has_defaults = any(l.get("is_defaulted") for l in existing_loans)
    dpd_30 = sum(int(l.get("dpd_30_plus") or 0) for l in existing_loans)
    if has_defaults or dpd_30 > 2:
        is_reject = True
        risk_factors.append({
            "code": "PAST_DEFAULT_RECORD",
            "severity": "HIGH",
            "message": f"Customer has active defaults or {dpd_30} instances of 30+ Days Past Due (DPD) payments."
        })

    # Rule 5: Collateral LTV Check
    if requested_amount > 20000 and calculated_ltv > 85.0:
        is_refer = True
        risk_factors.append({
            "code": "HIGH_LTV_RATIO",
            "severity": "MEDIUM",
            "message": f"Loan-to-Value (LTV) ratio of {calculated_ltv:.1f}% exceeds target threshold of 85.0%."
        })
        missing_info.append("Additional liquid collateral or guarantor declaration.")

    # Check for missing income documentation
    if monthly_income <= 0:
        missing_info.append("Latest 6 months bank statements or salary slips for income verification.")

    # Final Verdict Assembler
    if is_reject:
        verdict = "REJECT"
    elif is_refer:
        verdict = "REFER"
    else:
        verdict = "APPROVE"

    verified_facts = {
        "monthly_income": monthly_income,
        "credit_score": credit_score,
        "existing_monthly_debt": existing_emi_sum,
        "proposed_monthly_emi": round(proposed_emi, 2),
        "total_requested": requested_amount,
        "collateral_type": limits_collateral.get("collateral_type", "None") if limits_collateral else "None",
        "collateral_value": collateral_val
    }

    return verdict, round(calculated_dti, 2), round(calculated_ltv, 2), risk_factors, missing_info, verified_facts