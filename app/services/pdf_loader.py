"""
pdf_loader.py

Service for discovering, opening, and extracting page-level text 
and metadata from RBI bank policy PDFs using PyMuPDF (pymupdf) and pathlib.
"""

from pathlib import Path
from typing import List, Dict, Any
import pymupdf as fitz  # Updated import to eliminate PyMuPDF deprecation warning
import logging

logger = logging.getLogger("pdf_loader")
logging.basicConfig(level=logging.INFO)


def extract_category_from_path(pdf_path: Path, base_dir: Path) -> str:
    """
    Extracts policy category from parent directory name.
    E.g., '01_kyc' -> 'kyc', '02_deposits' -> 'deposits'
    """
    try:
        relative_path = pdf_path.relative_to(base_dir)
        parent_folder = relative_path.parent.name
        
        if "_" in parent_folder:
            parts = parent_folder.split("_", 1)
            if parts[0].isdigit():
                return parts[1].lower()
        return parent_folder.lower() if parent_folder else "uncategorized"
    except ValueError:
        return "uncategorized"


def load_single_pdf(pdf_path: Path, base_dir: Path) -> List[Dict[str, Any]]:
    """
    Loads a single PDF file, extracts text page-by-page, and returns structured metadata.
    """
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF file not found at path: {pdf_path}")

    if pdf_path.suffix.lower() != ".pdf":
        raise ValueError(f"File '{pdf_path.name}' is not a valid PDF document.")

    category = extract_category_from_path(pdf_path, base_dir)
    extracted_pages: List[Dict[str, Any]] = []

    try:
        doc = fitz.open(pdf_path)
    except Exception as err:
        raise RuntimeError(f"Failed to open or parse PDF '{pdf_path.name}': {str(err)}") from err

    try:
        if doc.is_encrypted:
            raise RuntimeError(f"PDF '{pdf_path.name}' is encrypted/password protected.")

        if doc.page_count == 0:
            logger.warning(f"PDF '{pdf_path.name}' contains 0 pages.")
            return []

        for page_num in range(len(doc)):
            page = doc[page_num]
            raw_text = page.get_text("text").strip()

            if not raw_text:
                logger.warning(
                    f"Empty or non-extractable text on Page {page_num + 1} of '{pdf_path.name}'."
                )

            page_data = {
                "document": pdf_path.name,
                "category": category,
                "page": page_num + 1,  # 1-indexed page numbering
                "text": raw_text,
                "file_path": str(pdf_path.resolve())
            }
            extracted_pages.append(page_data)

    finally:
        doc.close()

    return extracted_pages


def load_all_policy_pdfs(policies_dir: Path) -> Dict[str, Any]:
    """
    Recursively scans policies directory and extracts text across all PDF documents.
    """
    if not policies_dir.exists() or not policies_dir.is_dir():
        raise FileNotFoundError(f"Policies base directory does not exist: {policies_dir}")

    pdf_files = sorted(list(policies_dir.rglob("*.pdf")))
    
    if not pdf_files:
        logger.warning(f"No PDF files found inside directory: {policies_dir}")

    all_pages: List[Dict[str, Any]] = []
    processed_docs: List[str] = []
    errors: List[Dict[str, str]] = []

    for pdf_path in pdf_files:
        try:
            pages = load_single_pdf(pdf_path, base_dir=policies_dir)
            all_pages.extend(pages)
            processed_docs.append(pdf_path.name)
        except Exception as e:
            logger.error(f"Error processing '{pdf_path.name}': {str(e)}")
            errors.append({"document": pdf_path.name, "error": str(e)})

    return {
        "total_documents_found": len(pdf_files),
        "total_documents_processed": len(processed_docs),
        "total_pages_extracted": len(all_pages),
        "pages": all_pages,
        "errors": errors
    }