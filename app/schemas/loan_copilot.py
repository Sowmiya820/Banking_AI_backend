from typing import List, Optional, Dict, Any, Union
from pydantic import BaseModel, Field


class LoanEvaluationRequest(BaseModel):
    application_id: str = Field(..., example="APP001")


class LoanApplicationListItem(BaseModel):
    application_id: str
    customer_id: int
    full_name: Optional[str] = "Unknown"
    requested_amount: float
    requested_tenure_months: int
    status: Optional[str] = "PENDING"


class UnderwritingDecisionResponse(BaseModel):
    application_id: str
    customer_id: int
    customer_name: str
    decision_verdict: str  # APPROVE, REJECT, REFER
    calculated_dti: float
    calculated_ltv: float
    credit_score: int
    kyc_status: str
    risk_factors: List[Union[str, Dict[str, Any]]] = []
    missing_information: List[Union[str, Dict[str, Any]]] = []
    verified_facts: Union[List[Any], Dict[str, Any]] = {}