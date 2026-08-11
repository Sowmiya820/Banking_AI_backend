"""
test_stage2.py

Verification script for Stage 2 Chunking & Metadata Preservation.
Verifies that all page text is chunked without losing page numbers or document categories.
"""

import sys
from pathlib import Path

# Add backend directory to module search path
current_file_dir = Path(__file__).resolve().parent
if (current_file_dir / "app").exists():
    sys.path.append(str(current_file_dir))

from app.services.pdf_loader import load_all_policy_pdfs
from app.services.text_chunker import chunk_extracted_pages


def resolve_policies_dir() -> Path:
    current_dir = Path(__file__).resolve().parent
    opt1 = current_dir / "data" / "policies"
    opt2 = current_dir / "backend" / "data" / "policies"
    return opt1 if opt1.exists() else opt2


def run_stage2_test():
    base_dir = resolve_policies_dir()

    print("==================================================")
    print("      STAGE 2: CHUNKING & METADATA TEST VERIFICATION")
    print("==================================================\n")

    # Step 1: Load Pages from Stage 1
    pdf_result = load_all_policy_pdfs(base_dir)
    raw_pages = pdf_result["pages"]

    print(f"Total Input Pages  : {len(raw_pages)}")

    # Step 2: Execute Chunking
    chunks = chunk_extracted_pages(raw_pages, chunk_size=800, chunk_overlap=150)
    print(f"Total Chunks Built : {len(chunks)}\n")

    if not chunks:
        print("[FAILURE] Zero chunks were generated.")
        sys.exit(1)

    # Step 3: Validate Metadata Integrity across Chunks
    documents_seen = set()
    categories_seen = set()
    missing_metadata_count = 0

    for chunk in chunks:
        documents_seen.add(chunk["document"])
        categories_seen.add(chunk["category"])

        # Integrity Check
        if not chunk["document"] or not chunk["category"] or chunk["page"] < 1 or not chunk["chunk_id"]:
            missing_metadata_count += 1

    print("--------------------------------------------------")
    print(f"Unique Documents In Chunks : {len(documents_seen)} -> {sorted(list(documents_seen))}")
    print(f"Unique Categories Identified: {len(categories_seen)} -> {sorted(list(categories_seen))}")
    print(f"Metadata Integrity Violations: {missing_metadata_count}")
    print("--------------------------------------------------\n")

    # Step 4: Display Sample Chunk Output
    sample = chunks[0]
    print("--- SAMPLE GENERATED CHUNK ---")
    print(f"Chunk ID    : {sample['chunk_id']}")
    print(f"Document    : {sample['document']}")
    print(f"Category    : {sample['category']}")
    print(f"Page Number : {sample['page']}")
    print(f"Char Count  : {sample['char_count']}")
    print(f"Text Snippet: {sample['text'][:250]}...")
    print("------------------------------\n")

    if missing_metadata_count == 0 and len(documents_seen) == 4:
        print("==================================================")
        print("STAGE 2 VERIFICATION VERDICT: CHUNKING PASSED SUCCESSFULLY")
        print("==================================================")
    else:
        print("==================================================")
        print("STAGE 2 VERIFICATION VERDICT: FAILED METADATA CHECKS")
        print("==================================================")


if __name__ == "__main__":
    run_stage2_test()