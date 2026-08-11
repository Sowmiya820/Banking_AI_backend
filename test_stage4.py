"""
test_stage4.py

Verification script for Stage 4 End-to-End RAG Engine with Groq.
Executes policy queries through ChromaDB retrieval + Groq Llama-3.3 response generation.
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Automatically load environment variables from .env file if present
load_dotenv()

current_file_dir = Path(__file__).resolve().parent
if (current_file_dir / "app").exists():
    sys.path.append(str(current_file_dir))

from app.services.vector_store import initialize_vector_db
from app.services.rag_engine import answer_policy_query


def resolve_paths():
    current_dir = Path(__file__).resolve().parent
    chroma_dir = current_dir / "data" / "chroma_db"
    if not chroma_dir.exists():
        chroma_dir = current_dir / "backend" / "data" / "chroma_db"
    return chroma_dir


def run_stage4_test():
    print("==================================================")
    print("      STAGE 4: FULL RAG + GROQ API VERIFICATION   ")
    print("==================================================\n")

    # Verify Groq API key is present
    if not os.environ.get("GROQ_API_KEY"):
        print("[FAILURE] GROQ_API_KEY environment variable is missing.")
        print("Please set it in your .env file or run in PowerShell:")
        print("  $env:GROQ_API_KEY='your_groq_api_key_here'")
        sys.exit(1)

    chroma_dir = resolve_paths()
    collection = initialize_vector_db(chroma_dir)

    test_queries = [
        {"query": "What are the required documents for identity verification under KYC?", "category": "kyc"},
        {"query": "What is the penalty for premature closure of a fixed deposit?", "category": "deposits"},
        {"query": "When is an asset classified as a Non-Performing Asset (NPA)?", "category": "loans"}
    ]

    all_passed = True

    for idx, test in enumerate(test_queries, 1):
        q = test["query"]
        cat = test["category"]

        print(f"--------------------------------------------------")
        print(f"QUERY #{idx} [{cat.upper()}]: {q}")
        print("--------------------------------------------------")

        try:
            result = answer_policy_query(
                collection=collection,
                query=q,
                top_k=2,
                category_filter=cat
            )

            print("\n⚡ GROQ LLM EXPLANATION:")
            print(result["explanation"])

            print("\n📖 VERIFIED CITATIONS:")
            for cite in result["citations"]:
                print(f"  • Doc: {cite['document']} | Page #{cite['page']} | Score: {cite['similarity_score']}")
                print(f"    Snippet: \"{cite['quoted_snippet']}\"")

            print("\nSTATUS: [SUCCESS]\n")

        except Exception as e:
            print(f"\nSTATUS: [FAILURE] Error: {str(e)}\n")
            all_passed = False

    print("==================================================")
    if all_passed:
        print("STAGE 4 VERIFICATION VERDICT: RAG + GROQ PIPELINE PASSED")
    else:
        print("STAGE 4 VERIFICATION VERDICT: FAILED RAG ENGINE TEST")
    print("==================================================")


if __name__ == "__main__":
    run_stage4_test()