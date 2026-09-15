"""Local embedding provider — zero external API dependency.

Uses scikit-learn's HashingVectorizer + TruncatedSVD to produce
fixed-dimension vectors (1536-dim by default, matching pgvector schema).

This is a STATELESS, DETERMINISTIC embedding approach:
- No model downloads
- No GPU needed
- No API keys
- Works for any text (including CJK characters)
- Produces consistent vectors across runs

The quality is below dedicated embedding models (no semantic understanding
beyond n-gram co-occurrence), but it enables the RAG pipeline to function
immediately without any external dependencies. Upgrade path: replace this
module with sentence-transformers or an API provider when available.
"""

from __future__ import annotations

import logging
import math
import hashlib
from typing import Any

import numpy as np
from sklearn.feature_extraction.text import HashingVectorizer
from sklearn.decomposition import TruncatedSVD
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import Normalizer

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

TARGET_DIMS = 1536        # Matches pgvector vector(1536) column
VECTORIZER_N_FEATURES = TARGET_DIMS  # Hash space same as target dims — no truncation needed
SVD_N_COMPONENTS = 384         # Intermediate dim (cheaper than 1536)


# ---------------------------------------------------------------------------
# Embedder — lazy singleton pattern
# ---------------------------------------------------------------------------

class _LocalEmbedder:
    """Lazy-initialized sklearn embedding pipeline.

    Uses HashingVectorizer (stateless, no training) → Normalizer → 
    repeat/pad to TARGET_DIMS.
    """

    _instance: _LocalEmbedder | None = None

    def __init__(self) -> None:
        self._vectorizer = HashingVectorizer(
            n_features=VECTORIZER_N_FEATURES,
            ngram_range=(1, 3),    # unigrams + bigrams + trigrams
            analyzer="char_wb",     # char-based (good for CJK + mixed languages)
            norm="l2",
            alternate_sign=False,
        )
        self._initialized = True

    @classmethod
    def get_instance(cls) -> _LocalEmbedder:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate fixed-dimension vectors for a list of texts.

        Returns list of TARGET_DIMS-dimensional vectors (normalized L2).
        """
        if not texts:
            return []

        # HashingVectorizer → dense array
        sparse = self._vectorizer.transform(texts)
        dense = sparse.toarray().astype(np.float64)

        # L2-normalize
        norms = np.linalg.norm(dense, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        dense = dense / norms

        # If our hash space < TARGET_DIMS, pad with zeros
        # If > TARGET_DIMS, truncate
        if dense.shape[1] < TARGET_DIMS:
            padded = np.zeros((dense.shape[0], TARGET_DIMS), dtype=np.float64)
            padded[:, : dense.shape[1]] = dense
            dense = padded
        elif dense.shape[1] > TARGET_DIMS:
            dense = dense[:, :TARGET_DIMS]

        # Re-normalize after padding/truncation
        norms = np.linalg.norm(dense, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        dense = dense / norms

        return dense.tolist()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def local_embed(texts: list[str]) -> list[list[float]]:
    """Compute local TF-IDF-style embeddings.

    Args:
        texts: List of text strings to embed.

    Returns:
        List of vectors, each TARGET_DIMS (1536) floats, L2-normalized.
    """
    try:
        embedder = _LocalEmbedder.get_instance()
        return embedder.embed(texts)
    except Exception:
        logger.exception("Local embedding failed")
        # Fallback: deterministic hash-based vector
        return [_hash_vector(t) for t in texts]


def _hash_vector(text: str) -> list[float]:
    """Last-resort fallback: deterministic hash-based vector (1536-dim)."""
    # Use SHA-256 to produce deterministic components
    vec = [0.0] * TARGET_DIMS
    if not text:
        return vec

    # For each dimension, compute a hash of the text + dimension index
    # This is deterministic and distributes uniformly
    for i in range(min(TARGET_DIMS, 512)):  # Only fill first 512 for speed
        h = hashlib.sha256(f"{text}:{i}".encode()).digest()
        val = int.from_bytes(h[:4], "big") / 2**32
        vec[i] = (val * 2) - 1  # Normalize to [-1, 1]

    # L2-normalize
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [v / norm for v in vec]

    return vec


# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

SUPPORTS_BATCH = True
DIMS = TARGET_DIMS
PROVIDER_NAME = "local-tfidf"


__all__ = [
    "local_embed",
    "TARGET_DIMS",
    "SUPPORTS_BATCH",
    "DIMS",
    "PROVIDER_NAME",
]
