import os
import json
from fastapi import APIRouter
from pydantic import BaseModel, Field
from typing import List, Optional

router = APIRouter(prefix="/letter-writer", tags=["Module A4: Bank Letter Writer"])

class LetterRequest(BaseModel):
    customer_id: str = Field(..., example="CUST001")
    customer_name: Optional[str] = Field(default="Valued Customer", example="Jane Doe")
    loan_type: Optional[str] = Field(default="Personal Loan", example="Personal Loan")
    decision: str = Field(..., example="REFER") # APPROVED, REJECTED, REFER
    reason: str = Field(..., example="Additional information required")
    missing_info: Optional[str] = Field(default="Employment duration", example="Employment duration")

class FactItem(BaseModel):
    label: str
    detail: str
    is_used: bool = True

class LetterResponse(BaseModel):
    status: str = "success"
    letter_text: str
    facts_used: List[FactItem]
    evaluator: str = "Groq Plain-Language Engine"

@router.post("/generate", response_model=LetterResponse)
async def generate_bank_letter(payload: LetterRequest):
    groq_api_key = os.getenv("GROQ_API_KEY")

    # Construct the facts checklist
    facts = [
        FactItem(label="Customer Information", detail=f"{payload.customer_name} (ID: {payload.customer_id})", is_used=True),
        FactItem(label="Loan Application Type", detail=payload.loan_type or "Personal Loan", is_used=True),
        FactItem(label="Decision Outcome", detail=payload.decision.upper(), is_used=True),
        FactItem(label="Primary Decision Reason", detail=payload.reason, is_used=True),
    ]
    if payload.missing_info and payload.decision.upper() == "REFER":
        facts.append(FactItem(label="Missing Information Required", detail=payload.missing_info, is_used=True))

    if groq_api_key:
        try:
            from groq import Groq
            client = Groq(api_key=groq_api_key)
            
            prompt = f"""
You are an expert plain-language banking communication assistant. Convert these verified underwriting facts into a polite, empathetic, professional letter:

FACTS:
- Customer Name: {payload.customer_name} (ID: {payload.customer_id})
- Application Type: {payload.loan_type}
- Decision: {payload.decision}
- Underwriting Reason: {payload.reason}
- Action / Missing Info Required: {payload.missing_info if payload.missing_info else 'None'}

INSTRUCTIONS:
1. Express clear appreciation for their application.
2. State the decision clearly using non-jargon plain English.
3. If decision is REFER, clearly explain what documentation is missing.
4. Keep paragraph length short (2-3 sentences max per paragraph).

Return JSON format:
{{
    "letter_text": "Dear [Name],\\n\\n[Body text]\\n\\nRegards,\\nBank Application Review Team"
}}
"""
            completion = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.3,
            )
            
            llm_res = json.loads(completion.choices[0].message.content)
            return LetterResponse(
                letter_text=llm_res.get("letter_text", ""),
                facts_used=facts,
                evaluator="Groq LLM Engine"
            )
        except Exception as e:
            print(f"[Letter Writer Fallback] LLM Error: {e}")

    # Fallback Rule Generator
    salutation = f"Dear {payload.customer_name},"
    if payload.decision.upper() == "REFER":
        body = (
            f"Thank you for your application for a {payload.loan_type}.\n\n"
            "We have reviewed the information currently available to us. Additional information is required before we can complete the assessment.\n\n"
            f"Please provide details regarding your {payload.missing_info or 'employment duration'}.\n\n"
            "Once we receive the required information, we can continue processing your application."
        )
    elif payload.decision.upper() == "APPROVED":
        body = (
            f"We are pleased to inform you that your application for a {payload.loan_type} has been conditionally approved!\n\n"
            f"Reason: {payload.reason}.\n\n"
            "Our team will reach out shortly to finalize application paperwork."
        )
    else:
        body = (
            f"Thank you for applying for a {payload.loan_type} with us.\n\n"
            f"After review, we regret to inform you that we cannot approve your application at this time.\n\n"
            f"Reason: {payload.reason}."
        )

    return LetterResponse(
        letter_text=f"{salutation}\n\n{body}\n\nRegards,\nBank Application Review Team",
        facts_used=facts,
        evaluator="Rule Engine (Fallback)"
    )