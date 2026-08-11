"""
text_chunker.py

Service for chunking extracted PDF page text while preserving page-level
and document-level metadata required for accurate RAG citations.
"""

from typing import List, Dict, Any
import logging

logger = logging.getLogger("text_chunker")


def chunk_text_by_delimiter(
    text: str, 
    chunk_size: int = 800, 
    chunk_overlap: int = 150
) -> List[str]:
    """
    Splits text into overlapping chunks using natural boundary separators 
    (paragraphs, sentences, spaces).

    Args:
        text (str): Raw string text from a single page.
        chunk_size (int): Target maximum characters per chunk.
        chunk_overlap (int): Overlap character count between consecutive chunks.

    Returns:
        List[str]: List of text chunks.
    """
    if not text or not text.strip():
        return []

    if len(text) <= chunk_size:
        return [text.strip()]

    separators = ["\n\n", "\n", ". ", " ", ""]
    chunks: List[str] = []
    
    start = 0
    text_len = len(text)

    while start < text_len:
        end = start + chunk_size

        if end >= text_len:
            chunk = text[start:].strip()
            if chunk:
                chunks.append(chunk)
            break

        # Find best natural break point backwards from target end position
        split_pos = -1
        for sep in separators:
            if sep == "":
                split_pos = end
                break
            
            idx = text.rfind(sep, start + chunk_overlap, end)
            if idx != -1:
                split_pos = idx + len(sep)
                break

        if split_pos == -1 or split_pos <= start:
            split_pos = end

        chunk = text[start:split_pos].strip()
        if chunk:
            chunks.append(chunk)

        # Advance start pointer considering overlap
        start = max(start + 1, split_pos - chunk_overlap)

    return chunks


def chunk_extracted_pages(
    pages: List[Dict[str, Any]], 
    chunk_size: int = 800, 
    chunk_overlap: int = 150
) -> List[Dict[str, Any]]:
    """
    Processes extracted pages from Stage 1 and generates metadata-rich chunks.

    Args:
        pages (List[Dict[str, Any]]): Page dictionaries output from pdf_loader.py.
        chunk_size (int): Target character limit per chunk.
        chunk_overlap (int): Character overlap between adjacent chunks.

    Returns:
        List[Dict[str, Any]]: List of chunk dictionaries containing full metadata.
    """
    all_chunks: List[Dict[str, Any]] = []

    for page_info in pages:
        raw_text = page_info.get("text", "")
        if not raw_text.strip():
            continue

        text_chunks = chunk_text_by_delimiter(
            text=raw_text,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap
        )

        doc_name = page_info["document"]
        page_num = page_info["page"]
        category = page_info["category"]

        for idx, chunk_text in enumerate(text_chunks):
            chunk_id = f"{doc_name}_p{page_num}_c{idx}"
            
            chunk_entry = {
                "chunk_id": chunk_id,
                "document": doc_name,
                "category": category,
                "page": page_num,
                "chunk_index": idx,
                "char_count": len(chunk_text),
                "text": chunk_text,
                "file_path": page_info.get("file_path", "")
            }
            all_chunks.append(chunk_entry)

    logger.info(f"Generated {len(all_chunks)} chunks from {len(pages)} pages.")
    return all_chunks