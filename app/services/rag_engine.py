"""
rag_engine.py

Service for orchestrating Retrieval-Augmented Generation (RAG):
1. Retrieves top relevant policy chunks from ChromaDB.
2. Formats a strict system prompt with retrieved context and page metadata.
3. Invokes Groq API (Llama 3.3 70B) to generate grounded answers with cited sources.
"""

import os
import logging
from typing import List, Dict, Any, Optional
from groq import Groq

from app.services.vector_store import query_similar_chunks

logger = logging.getLogger("rag_engine")

# High-speed production model on Groq
DEFAULT_MODEL = "llama-3.3-70b-versatile"


def format_context_blocks(retrieved_chunks: List[Dict[str, Any]]) -> str:
    """
    Formats retrieved vector chunks into a structured context string for Groq.
    """
    context_parts = []
    for idx, chunk in enumerate(retrieved_chunks, 1):
        block = (
            f"--- SOURCE ITEM [{idx}] ---\n"
            f"Document: {chunk['document']}\n"
            f"Category: {chunk['category']}\n"
            f"Page Number: {chunk['page']}\n"
            f"Content:\n{chunk['text']}\n"
        )
        context_parts.append(block)

    return "\n".join(context_parts)


def answer_policy_query(
    collection: Any,
    query: str,
    top_k: int = 3,
    category_filter: Optional[str] = None,
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    Executes full RAG workflow for a given bank policy question.

    Args:
        collection: Active ChromaDB collection object.
        query (str): User policy question.
        top_k (int): Number of context chunks to retrieve.
        category_filter (Optional[str]): Optional category filter ('kyc', 'deposits', etc.).
        api_key (Optional[str]): Groq API key (defaults to GROQ_API_KEY env var).

    Returns:
        Dict[str, Any]: Object containing Groq explanation and list of cited sources.
    """
    groq_key = api_key or os.environ.get("GROQ_API_KEY")
    if not groq_key:
        raise ValueError(
            "GROQ_API_KEY environment variable is not set. "
            "Ensure it is defined in your .env or set via $env:GROQ_API_KEY='your_key'"
        )

    # 1. Retrieve top context chunks from ChromaDB
    retrieved_chunks = query_similar_chunks(
        collection=collection,
        query_text=query,
        top_k=top_k,
        category_filter=category_filter
    )

    if not retrieved_chunks:
        return {
            "query": query,
            "explanation": "No relevant bank policy context found for your query in the database.",
            "citations": []
        }

    # 2. Format context for prompt
    formatted_context = format_context_blocks(retrieved_chunks)

    # 3. Construct System Instructions & User Prompt enforcing strict grounding & clear structure
    system_instruction = (
        "You are an enterprise RBI Bank Policy Explainer AI.\n"
        "Answer the user's query using ONLY the provided policy context below.\n"
        "Do NOT use outside knowledge or assume unstated rules.\n"
        "If the context does not contain enough information, state that clearly.\n\n"
        "Formatting & Clarity Rules:\n"
        "1. Always format your answer as clear, short bullet points (2-4 bullet points maximum).\n"
        "2. Explicitly distinguish between full premature withdrawals vs. penalty-free partial allowances.\n"
        "3. Always clarify that interest penalties reduce the interest rate earned, NOT the principal balance. Never state money is taken off the principal or use confusing terms like 'balance broken'.\n"
        "4. Do not combine multiple conditions into a single run-on sentence. Put each distinct rule or condition on its own bullet point.\n"
        "5. Do not invent clause numbers or policies not present in the text."
    )

    user_prompt = f"""
POLICY CONTEXT:
{formatted_context}

USER QUESTION: {query}

INSTRUCTIONS: Summarize the policy answer strictly using the provided context, following all bullet-point and financial term accuracy rules.
"""

    # 4. Invoke Groq API
    client = Groq(api_key=groq_key)
    
    chat_completion = client.chat.completions.create(
        messages=[
            {
                "role": "system",
                "content": system_instruction
            },
            {
                "role": "user",
                "content": user_prompt
            }
        ],
        model=DEFAULT_MODEL,
        temperature=0.0  # Zero temperature for deterministic factual output
    )

    explanation_text = chat_completion.choices[0].message.content.strip()

    # 5. Extract structured citation objects
    citations = [
        {
            "document": chunk["document"],
            "category": chunk["category"],
            "page": chunk["page"],
            "chunk_id": chunk["chunk_id"],
            "similarity_score": chunk["similarity_score"],
            "quoted_snippet": chunk["text"][:250].strip() + "..."
        }
        for chunk in retrieved_chunks
    ]

    return {
        "query": query,
        "explanation": explanation_text,
        "citations": citations
    }