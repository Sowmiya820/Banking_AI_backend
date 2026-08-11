"""
vector_store.py

Service for initializing ChromaDB persistent storage, batch-embedding text chunks
using SentenceTransformers ('all-MiniLM-L6-v2'), and performing similarity searches.
"""

import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

import chromadb
from chromadb.utils import embedding_functions

logger = logging.getLogger("vector_store")
logging.basicConfig(level=logging.INFO)

COLLECTION_NAME = "enterprise_bank_policies"
DEFAULT_EMBEDDING_MODEL = "all-MiniLM-L6-v2"


def get_embedding_function(model_name: str = DEFAULT_EMBEDDING_MODEL):
    """
    Returns SentenceTransformer embedding function for ChromaDB.
    """
    return embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=model_name
    )


def initialize_vector_db(chroma_dir: Path) -> chromadb.Collection:
    """
    Initializes a persistent ChromaDB client and creates or fetches the collection.

    Args:
        chroma_dir (Path): Path to persistent storage directory.

    Returns:
        chromadb.Collection: Active collection instance.
    """
    chroma_dir.mkdir(parents=True, exist_ok=True)
    
    client = chromadb.PersistentClient(path=str(chroma_dir.resolve()))
    embedding_fn = get_embedding_function()

    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=embedding_fn,
        metadata={"hnsw:space": "cosine"}
    )
    return collection


def index_chunks(
    collection: chromadb.Collection, 
    chunks: List[Dict[str, Any]], 
    batch_size: int = 200
) -> int:
    """
    Batch inserts chunks with full metadata into ChromaDB.

    Args:
        collection (chromadb.Collection): Target collection.
        chunks (List[Dict[str, Any]]): List of chunk dictionaries from Stage 2.
        batch_size (int): Batch size limit to prevent memory spikes.

    Returns:
        int: Total number of chunks successfully indexed.
    """
    if not chunks:
        logger.warning("No chunks provided for indexing.")
        return 0

    total_chunks = len(chunks)
    logger.info(f"Indexing {total_chunks} chunks into collection '{COLLECTION_NAME}'...")

    for i in range(0, total_chunks, batch_size):
        batch = chunks[i : i + batch_size]
        
        ids = [c["chunk_id"] for c in batch]
        documents = [c["text"] for c in batch]
        metadatas = [
            {
                "document": c["document"],
                "category": c["category"],
                "page": int(c["page"]),
                "chunk_index": int(c["chunk_index"]),
                "char_count": int(c["char_count"]),
                "file_path": c.get("file_path", "")
            }
            for c in batch
        ]

        # Upsert ensures idempotent indexing (re-running will update rather than duplicate)
        collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas
        )

    logger.info(f"Successfully indexed {total_chunks} chunks into ChromaDB.")
    return total_chunks


def query_similar_chunks(
    collection: chromadb.Collection,
    query_text: str,
    top_k: int = 3,
    category_filter: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Performs vector similarity search against ChromaDB collection.

    Args:
        collection (chromadb.Collection): ChromaDB collection instance.
        query_text (str): Input query string.
        top_k (int): Number of top matches to retrieve.
        category_filter (Optional[str]): Metadata category filter (e.g., 'kyc', 'loans').

    Returns:
        List[Dict[str, Any]]: Matched chunks sorted by similarity score.
    """
    where_filter = {"category": category_filter.lower()} if category_filter else None

    results = collection.query(
        query_texts=[query_text],
        n_results=top_k,
        where=where_filter,
        include=["documents", "metadatas", "distances"]
    )

    formatted_results = []
    
    if not results or not results["ids"] or not results["ids"][0]:
        return formatted_results

    ids = results["ids"][0]
    docs = results["documents"][0]
    metas = results["metadatas"][0]
    distances = results["distances"][0]

    for chunk_id, doc, meta, dist in zip(ids, docs, metas, distances):
        # Convert cosine distance to similarity score (cosine distance in Chroma = 1 - cosine_similarity)
        similarity_score = max(0.0, round(1.0 - dist, 4))
        
        formatted_results.append({
            "chunk_id": chunk_id,
            "document": meta.get("document", ""),
            "category": meta.get("category", ""),
            "page": meta.get("page", 0),
            "similarity_score": similarity_score,
            "distance": round(dist, 4),
            "text": doc
        })

    return formatted_results