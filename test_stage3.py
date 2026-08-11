"""
test_stage3.py

Verification script for Stage 3 Vector Embeddings & Similarity Retrieval.
Indexes chunks into ChromaDB and verifies query retrieval across policy categories.
"""

import sys
from pathlib import Path

current_file_dir = Path(__file__).resolve().parent
if (current_file_dir / "app").exists():
    sys.path.append(str(current_file_dir))

from app.services.pdf_loader import load_all_policy_pdfs
from app.services.text_chunker import chunk_extracted_pages
from app.services.vector_store import (
    initialize_vector_db,
    index_chunks,
    query_similar_chunks
)


def resolve_paths():
    current_dir = Path(__file__).resolve().parent
    policies_dir = current_dir / "data" / "policies"
    chroma_dir = current_dir / "data" / "chroma_db"

    if not policies_dir.exists():
        policies_dir = current_dir / "backend" / "data" / "policies"
        chroma_dir = current_dir / "backend" / "data" / "chroma_db"

    return policies_dir, chroma_dir


def run_stage3_test():
    policies_dir, chroma_dir = resolve_paths()

    print("==================================================")
    print("      STAGE 3: VECTOR STORE & RETRIEVAL TEST      ")
    print("==================================================\n")
    print(f"Policies Folder : {policies_dir}")
    print(f"ChromaDB Folder : {chroma_dir}\n")

    # 1. Load PDFs and Chunk
    pdf_res = load_all_policy_pdfs(policies_dir)
    chunks = chunk_extracted_pages(pdf_res["pages"], chunk_size=800, chunk_overlap=150)
    print(f"Input Chunks Prepared: {len(chunks)}\n")

    # 2. Initialize ChromaDB and Index Chunks
    collection = initialize_vector_db(chroma_dir)
    indexed_count = index_chunks(collection, chunks)
    
    stored_count = collection.count()
    print(f"ChromaDB Persistent Count: {stored_count} vectors\n")

    if stored_count == 0:
        print("[FAILURE] Vector store contains 0 documents.")
        sys.exit(1)

    # 3. Test Retrieval Queries
    test_queries = [
        {"query": "What documents are required for customer identification in KYC?", "filter": "kyc"},
        {"query": "What is the penalty for early closure or premature deposit withdrawal?", "filter": "deposits"},
        {"query": "What are the rules for asset classification of non performing loans?", "filter": "loans"},
        {"query": "How do I file a complaint with the Banking Ombudsman?", "filter": "complaints"}
    ]

    all_queries_passed = True

    print("--------------------------------------------------")
    print("        EXECUTING SIMILARITY SEARCH TESTS         ")
    print("--------------------------------------------------\n")

    for idx, test in enumerate(test_queries, 1):
        q = test["query"]
        cat = test["filter"]
        
        results = query_similar_chunks(collection, query_text=q, top_k=2, category_filter=cat)

        print(f"Test #{idx} [{cat.upper()}] Query: '{q}'")
        if not results:
            print(f"STATUS: [FAILURE] Zero matches returned.\n")
            all_queries_passed = False
            continue

        top = results[0]
        print(f"  -> Matched ID    : {top['chunk_id']}")
        print(f"  -> Document      : {top['document']}")
        print(f"  -> Page Number   : {top['page']}")
        print(f"  -> Similarity    : {top['similarity_score']}")
        print(f"  -> Text Snippet  : {top['text'][:180].replace('\n', ' ')}...")
        print("STATUS: [SUCCESS]\n")

    print("==================================================")
    if all_queries_passed and stored_count >= len(chunks):
        print("STAGE 3 VERIFICATION VERDICT: VECTOR STORAGE PASSED SUCCESSFULLY")
    else:
        print("STAGE 3 VERIFICATION VERDICT: FAILED RETRIEVAL TESTS")
    print("==================================================")


if __name__ == "__main__":
    run_stage3_test()