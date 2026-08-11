import os
import json
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.db.models.models import User
from app.services.audit import log_audit_event
from app.core.dependencies import require_roles

# Safe Groq SDK check
try:
    from groq import Groq
    GROQ_SDK_AVAILABLE = True
except ImportError:
    GROQ_SDK_AVAILABLE = False

# Import RAG Service if available
try:
    from app.services.rag_engine import answer_policy_query
    RAG_SERVICE_AVAILABLE = True
except ImportError:
    RAG_SERVICE_AVAILABLE = False

router = APIRouter(prefix="/policy-explainer", tags=["Module A3: Bank Policy Explainer"])

# ------------------------------------------------------------------
# POLICY KNOWLEDGE BASE (Updated Grounded Mock Store)
# ------------------------------------------------------------------
MOCK_POLICY_DB = {
    "kyc": {
        "topic": "KYC & Identity Verification",
        "source": "KYC Policy — Section 3.2 (Customer Verification)",
        "category": "kyc",
        "page": 3,
        "answer": "• Proof of Identity: Customers must provide one valid government-issued photo ID (Passport, Driver's License, or State ID).\n• Proof of Address: One valid proof of residential address issued within the last 90 days is required prior to account activation.",
        "quoted_evidence": [
            "Valid government-issued photo ID (Passport, Driver's License, or State ID) is mandatory for identity verification.",
            "Proof of residential address (Utility bill, municipal tax receipt, or bank statement issued within the last 90 days) must be submitted."
        ]
    },
    "withdrawal": {
        "topic": "Term Deposit Liquidation",
        "source": "Deposit Account Terms — Section 5.1 (Early Withdrawal)",
        "category": "deposits",
        "page": 12,
        "answer": "• Interest Penalty: Premature liquidation of term deposits prior to stated maturity incurs a 0.50% reduction in the accumulated interest rate.\n• Principal Safety: The principal balance is 100% protected and never reduced or penalized.\n• Penalty-Free Exemption: Partial withdrawals up to 20% of principal balance are permitted once per calendar year without penalty.",
        "quoted_evidence": [
            "Premature liquidation of term deposits prior to stated maturity will incur a 0.50% reduction in accumulated interest.",
            "Partial withdrawals are permitted up to 20% of principal balance once per calendar year without penalty."
        ]
    },
    "fee": {
        "topic": "Fee Schedule & Charges",
        "source": "Fee Schedule 2026 — Section 1.4 (Account Maintenance)",
        "category": "deposits",
        "page": 5,
        "answer": "• Monthly Maintenance Fee: Standard checking accounts carry a $12 monthly maintenance fee.\n• Balance Waiver: Monthly fees are waived for account holders maintaining an average daily balance of $1,500 or higher.",
        "quoted_evidence": [
            "A monthly maintenance fee of $12.00 applies to standard checking accounts.",
            "Monthly fees are waived for account holders maintaining an average daily balance of $1,500 or higher."
        ]
    }
}


# ------------------------------------------------------------------
# SCHEMAS
# ------------------------------------------------------------------
class CitationItem(BaseModel):
    document: str
    category: str = "general"
    page: int = 1
    chunk_id: str = "chunk_0"
    similarity_score: float = 0.95
    quoted_snippet: str


class PolicyQuestionRequest(BaseModel):
    query: Optional[str] = Field(None, example="What is the penalty for early closure of a term deposit?")
    question: Optional[str] = Field(None, example="What documents are required for KYC?")
    category: Optional[str] = Field(None, example="deposits")
    top_k: int = Field(default=3, ge=1, le=10)

    @model_validator(mode="after")
    def validate_prompt(self):
        if not self.query and not self.question:
            raise ValueError("Either 'query' or 'question' field must be provided.")
        # Synchronize query and question
        if not self.query:
            self.query = self.question
        if not self.question:
            self.question = self.query
        return self


class PolicyResponse(BaseModel):
    status: str = "success"
    query: str
    question: str
    explanation: str
    answer: str
    source: str
    citations: List[CitationItem] = []
    quoted_evidence: List[str] = []
    evaluator: str = "Groq RAG Policy Engine"


# ------------------------------------------------------------------
# RETRIEVAL HELPER (Fallback Context Engine)
# ------------------------------------------------------------------
def retrieve_relevant_policy_context(question: str) -> Dict[str, Any]:
    """Keyword matching fallback retriever when ChromaDB collection is empty."""
    q = question.lower()
    if any(k in q for k in ["kyc", "document", "identity", "passport", "verify"]):
        return MOCK_POLICY_DB["kyc"]
    elif any(k in q for k in ["withdrawal", "liquidat", "penalty", "early", "break", "term deposit", "fixed deposit"]):
        return MOCK_POLICY_DB["withdrawal"]
    elif any(k in q for k in ["fee", "charge", "cost", "maintenance"]):
        return MOCK_POLICY_DB["fee"]
    
    return MOCK_POLICY_DB["withdrawal"]


# ------------------------------------------------------------------
# CORE BUSINESS LOGIC
# ------------------------------------------------------------------
async def process_policy_query(
    request: Request,
    payload: PolicyQuestionRequest,
    db: Optional[AsyncSession] = None,
    current_user: Optional[User] = None,
    endpoint_path: str = "/api/v1/policy-explainer/query"
) -> PolicyResponse:
    user_query = payload.query or payload.question or ""
    collection = getattr(request.app.state, "chroma_collection", None)

    # 1. Primary Vector RAG Execution (if ChromaDB collection is active and loaded)
    if RAG_SERVICE_AVAILABLE and collection is not None and collection.count() > 0:
        try:
            rag_result = answer_policy_query(
                collection=collection,
                query=user_query,
                top_k=payload.top_k,
                category_filter=payload.category
            )

            # Audit Logging
            if db and current_user:
                try:
                    await log_audit_event(
                        db=db,
                        user_id=current_user.user_id,
                        action="POLICY_EXPLAINER_QUERY",
                        endpoint=endpoint_path,
                        details=f"RAG ChromaDB Query: '{user_query[:50]}...'"
                    )
                except Exception as audit_err:
                    print(f"⚠️ [AUDIT LOG WARNING] Failed to record audit log: {audit_err}")

            explanation_text = rag_result.get("explanation", "")
            citations_list = rag_result.get("citations", [])
            primary_source = citations_list[0].get("document", "ChromaDB Policy Base") if citations_list else "ChromaDB Policy Store"
            evidence_quotes = [c.get("quoted_snippet", "") for c in citations_list if c.get("quoted_snippet")]

            return PolicyResponse(
                query=user_query,
                question=user_query,
                explanation=explanation_text,
                answer=explanation_text,
                source=primary_source,
                citations=[CitationItem(**c) if isinstance(c, dict) else c for c in citations_list],
                quoted_evidence=evidence_quotes,
                evaluator="ChromaDB + Groq RAG Engine"
            )
        except Exception as rag_err:
            print(f"⚠️ [Vector RAG Fallback] Error running Chroma RAG: {rag_err}")

    # 2. Direct Groq LLM Synthesis with Grounded Context
    groq_api_key = os.getenv("GROQ_API_KEY")
    grounded_context = retrieve_relevant_policy_context(user_query)

    if groq_api_key and GROQ_SDK_AVAILABLE:
        try:
            client = Groq(api_key=groq_api_key)

            prompt = f"""
You are an expert Bank Policy Explainer AI for an enterprise bank.
Answer the user's question USING ONLY the grounded policy context provided below.

GROUNDED POLICY CONTEXT:
Source Document: {grounded_context['source']}
Context Content: {grounded_context['answer']}
Verbatim Evidence: {json.dumps(grounded_context['quoted_evidence'])}

USER QUESTION:
"{user_query}"

CRITICAL INSTRUCTIONS:
1. Format your response strictly as 2-3 short bullet points starting with '•'.
2. Explicitly distinguish between interest rate reductions vs. principal balance safety. Never state principal is penalized or use terms like "balance broken".
3. Differentiate full premature withdrawals from penalty-free partial withdrawal allowances.
4. Use the source name verbatim as 'source'.
5. Quote verbatim sentences from the provided context as 'quoted_evidence'.

Respond ONLY in strict JSON matching this schema:
{{
    "answer": "• Bullet point 1\n• Bullet point 2",
    "source": "Exact source document string",
    "quoted_evidence": ["Exact quote 1", "Exact quote 2"]
}}
"""
            completion = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.0,
                max_tokens=500
            )

            llm_res = json.loads(completion.choices[0].message.content)
            ans = llm_res.get("answer", grounded_context["answer"])
            src = llm_res.get("source", grounded_context["source"])
            evidence = llm_res.get("quoted_evidence", grounded_context["quoted_evidence"])

            if db and current_user:
                try:
                    await log_audit_event(
                        db=db,
                        user_id=current_user.user_id,
                        action="POLICY_EXPLAINER_QUERY",
                        endpoint=endpoint_path,
                        details=f"Query: '{user_query[:50]}...' | Source: {src}"
                    )
                except Exception as audit_err:
                    print(f"⚠️ [AUDIT LOG WARNING] Failed to record audit log: {audit_err}")

            citations = [
                CitationItem(
                    document=src,
                    category=grounded_context.get("category", "general"),
                    page=grounded_context.get("page", 1),
                    chunk_id="chunk_1",
                    similarity_score=0.92,
                    quoted_snippet=ev
                ) for ev in evidence
            ]

            return PolicyResponse(
                query=user_query,
                question=user_query,
                explanation=ans,
                answer=ans,
                source=src,
                citations=citations,
                quoted_evidence=evidence,
                evaluator="Groq Grounded RAG Engine (llama-3.3-70b-versatile)"
            )

        except Exception as e:
            print(f"⚠️ [Policy Explainer LLM Fallback] Error: {e}")

    # 3. Rule Engine Fallback Context Grounding
    if db and current_user:
        try:
            await log_audit_event(
                db=db,
                user_id=current_user.user_id,
                action="POLICY_EXPLAINER_QUERY",
                endpoint=endpoint_path,
                details=f"Query: '{user_query[:50]}...' | Fallback Engine Used"
            )
        except Exception as audit_err:
            print(f"⚠️ [AUDIT LOG WARNING] Failed to record audit log: {audit_err}")

    citations = [
        CitationItem(
            document=grounded_context["source"],
            category=grounded_context.get("category", "general"),
            page=grounded_context.get("page", 1),
            chunk_id="chunk_fallback",
            similarity_score=0.88,
            quoted_snippet=ev
        ) for ev in grounded_context["quoted_evidence"]
    ]

    return PolicyResponse(
        query=user_query,
        question=user_query,
        explanation=grounded_context["answer"],
        answer=grounded_context["answer"],
        source=grounded_context["source"],
        citations=citations,
        quoted_evidence=grounded_context["quoted_evidence"],
        evaluator="Rule Engine (Fallback Context Grounding)"
    )


# ------------------------------------------------------------------
# ROUTE ENDPOINTS
# ------------------------------------------------------------------
@router.post("/query", response_model=PolicyResponse)
async def query_policy_endpoint(
    request: Request,
    payload: PolicyQuestionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(require_roles(["RELATIONSHIP MANAGER", "RELATIONSHIP_MANAGER", "LOAN OFFICER", "LOAN_OFFICER", "CUSTOMER", "ADMIN"]))
):
    """Primary REST API Endpoint for Stage 5 RAG Policy Queries (`/query`)."""
    return await process_policy_query(
        request=request,
        payload=payload,
        db=db,
        current_user=current_user,
        endpoint_path="/api/v1/policy-explainer/query"
    )


@router.post("/ask", response_model=PolicyResponse)
async def ask_policy_question_endpoint(
    request: Request,
    payload: PolicyQuestionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(require_roles(["RELATIONSHIP MANAGER", "RELATIONSHIP_MANAGER", "LOAN OFFICER", "LOAN_OFFICER", "CUSTOMER", "ADMIN"]))
):
    """Alias REST API Endpoint (`/ask`)."""
    return await process_policy_query(
        request=request,
        payload=payload,
        db=db,
        current_user=current_user,
        endpoint_path="/api/v1/policy-explainer/ask"
    )