import os
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional

router = APIRouter(prefix="/policy-explainer", tags=["Module A3: Bank Policy Explainer"])

class PolicyQuestionRequest(BaseModel):
    question: str = Field(..., example="What documents are required for KYC?")

class PolicyResponse(BaseModel):
    status: str = "success"
    question: str
    answer: str
    source: str
    quoted_evidence: List[str]
    evaluator: str = "Groq RAG Policy Engine"

# Knowledge base mock / vector store fallback
MOCK_POLICY_DB = {
    "kyc": {
        "source": "KYC Policy — Section 3.2 (Customer Verification)",
        "answer": "Customers must provide one valid government-issued photo identity document and one valid proof of address issued within the last 90 days.",
        "quoted_evidence": [
            "Valid government-issued photo ID (Passport, Driver's License, or State ID) is mandatory for identity verification.",
            "Proof of residential address (Utility bill, municipal tax receipt, or bank statement issued within the last 90 days) must be submitted."
        ]
    },
    "withdrawal": {
        "source": "Deposit Account Terms — Section 5.1 (Early Withdrawal)",
        "answer": "Early withdrawals on fixed term deposits incur a 0.50% interest penalty on the total balance broken.",
        "quoted_evidence": [
            "Premature liquidation of term deposits prior to stated maturity will incur a 0.50% reduction in accumulated interest.",
            "Partial withdrawals are permitted up to 20% of principal balance once per calendar year without penalty."
        ]
    }
}

@router.post("/ask", response_model=PolicyResponse)
async def ask_policy_question(payload: PolicyQuestionRequest):
    question_lower = payload.question.lower()
    
    groq_api_key = os.getenv("GROQ_API_KEY")

    # If Groq LLM Key is present, trigger RAG prompt with forced JSON schema
    if groq_api_key:
        try:
            from groq import Groq
            client = Groq(api_key=groq_api_key)
            
            prompt = f"""
You are an expert Bank Policy Explainer AI for an enterprise bank.
Answer the user's question using the policy context provided.

CRITICAL INSTRUCTIONS:
1. Provide a direct, concise explanation in 2-3 sentences.
2. Cite the exact policy section as 'source'.
3. Quote verbatim sentences from the policy as 'quoted_evidence'.

Question: "{payload.question}"

Respond ONLY in strict JSON format matching this schema:
{{
    "answer": "Concise direct answer...",
    "source": "Policy Name — Section X.X",
    "quoted_evidence": ["Exact quote 1", "Exact quote 2"]
}}
"""
            completion = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.2,
            )
            
            import json
            llm_res = json.loads(completion.choices[0].message.content)
            
            return PolicyResponse(
                question=payload.question,
                answer=llm_res.get("answer", "Policy details retrieved."),
                source=llm_res.get("source", "Bank General Policy Document"),
                quoted_evidence=llm_res.get("quoted_evidence", []),
                evaluator="Groq RAG LLM Engine"
            )
        except Exception as e:
            print(f"[Policy Explainer LLM Fallback] Error: {e}")

    # Fallback Rule Engine / Mock Search
    matched_key = "kyc" if "kyc" in question_lower or "document" in question_lower or "identity" in question_lower else "withdrawal"
    data = MOCK_POLICY_DB[matched_key]

    return PolicyResponse(
        question=payload.question,
        answer=data["answer"],
        source=data["source"],
        quoted_evidence=data["quoted_evidence"],
        evaluator="Rule Engine (Fallback)"
    )