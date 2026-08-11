"""
test_stage1.py

Verification script for Stage 1 PDF Extraction.
Locates all 4 RBI policy PDFs, runs extraction, and validates outputs.
"""

import sys
from pathlib import Path

# Add backend directory to module search path dynamically
current_file_dir = Path(__file__).resolve().parent

if (current_file_dir / "app").exists():
    sys.path.append(str(current_file_dir))
elif (current_file_dir / "backend").exists():
    sys.path.append(str(current_file_dir / "backend"))

from app.services.pdf_loader import load_all_policy_pdfs, load_single_pdf


def resolve_policies_dir() -> Path:
    """
    Smart path locator to find data/policies whether script is executed
    from root directory or inside backend/ directory.
    """
    current_dir = Path(__file__).resolve().parent

    # Check relative options
    option1 = current_dir / "data" / "policies"
    option2 = current_dir / "backend" / "data" / "policies"

    if option1.exists():
        return option1
    if option2.exists():
        return option2

    # Fallback default
    return option1


def run_test():
    base_dir = resolve_policies_dir()

    print("==================================================")
    print("      STAGE 1: PDF EXTRACTION TEST VERIFICATION   ")
    print("==================================================\n")
    print(f"Target Policy Folder: {base_dir}\n")

    if not base_dir.exists():
        print(f"[FAILURE] Base policies directory does not exist at: {base_dir}")
        print("Please verify your directory contains: backend/data/policies/[categories]/[pdfs]")
        sys.exit(1)

    result = load_all_policy_pdfs(base_dir)

    print(f"Total PDFs Found     : {result['total_documents_found']}")
    print(f"Total PDFs Processed : {result['total_documents_processed']}")
    print(f"Total Pages Extracted: {result['total_pages_extracted']}\n")

    pdf_files = sorted(list(base_dir.rglob("*.pdf")))
    
    if not pdf_files:
        print("[FAILURE] No PDF files located in policies directory.")
        sys.exit(1)

    all_success = True

    for pdf_path in pdf_files:
        print("--------------------------------------------------")
        try:
            pages = load_single_pdf(pdf_path, base_dir=base_dir)
            
            if not pages:
                print(f"Document : {pdf_path.name}")
                print(f"[FAILURE] File processed but zero pages extracted.")
                all_success = False
                continue

            category = pages[0]["category"]
            page_count = len(pages)
            total_chars = sum(len(p["text"]) for p in pages)
            
            # Print clean text preview
            preview_text = pages[0]["text"][:300].replace("\n", " ") if pages[0]["text"] else "[EMPTY PAGE 1]"

            print(f"Document           : {pdf_path.name}")
            print(f"Category           : {category}")
            print(f"Number of Pages    : {page_count}")
            print(f"Extracted Chars    : {total_chars:,} characters")
            print(f"Page 1 Preview     : {preview_text}...")
            print("STATUS             : [SUCCESS]")

        except Exception as e:
            print(f"Document           : {pdf_path.name}")
            print(f"ERROR              : {str(e)}")
            print("STATUS             : [FAILURE]")
            all_success = False

    print("\n==================================================")
    if all_success and result["total_documents_processed"] == 4:
        print("STAGE 1 VERIFICATION VERDICT: ALL 4 PDFs PASSED SUCCESSFULLY")
    else:
        print("STAGE 1 VERIFICATION VERDICT: FAILED (Check errors above)")
    print("==================================================")


if __name__ == "__main__":
    run_test()