"""Embedding service.

Wraps ``sentence-transformers`` with auto-detected device. Provides a
deterministic ``FakeEmbedder`` for tests so we never download a model in CI.

Model choices (override via ``NOTEBOOKAI_EMB_MODEL``):

* **BAAI/bge-small-en-v1.5** *(default, 384-dim, ~33 MB)* — solid English
  retrieval baseline, sub-100 ms per chunk on M-series CPU.
* **Snowflake/snowflake-arctic-embed-s** *(384-dim, ~33 MB)* — drop-in
  alternative; beats bge-small on MTEB, identical sidecar bundle size.
* **BAAI/bge-m3** *(1024-dim, ~600 MB)* — multilingual, longer-context
  (8192 tokens), best quality. Bloats the desktop sidecar; gate behind
  the ``NOTEBOOKAI_EMB_LARGE=1`` opt-in described in ``.env.example``.

Switching models triggers an automatic index rebuild on next
:meth:`IndexBuilder.bootstrap` because the recorded model/dim no longer
match the live embedder. No manual rebuild step required.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:  # pragma: no cover
    from sentence_transformers import SentenceTransformer


def _auto_device() -> str:
    try:
        import torch  # type: ignore
    except Exception:
        return "cpu"
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


class Embedder:
    """Singleton-friendly embedder.

    Lazy-loads the model on the first call to :meth:`encode`.
    """

    DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"
    BATCH = 32

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        device: str | None = None,
    ) -> None:
        self.model_name = model_name
        self.device = device or _auto_device()
        self._model: SentenceTransformer | None = None
        self._dim: int | None = None

    # -- internals -------------------------------------------------------

    def _load(self) -> SentenceTransformer:
        if self._model is None:
            from sentence_transformers import SentenceTransformer  # heavy import

            self._model = SentenceTransformer(self.model_name, device=self.device)
            # `.get_sentence_embedding_dimension()` is the canonical way.
            self._dim = int(self._model.get_sentence_embedding_dimension())
        return self._model

    # -- public API ------------------------------------------------------

    @property
    def dim(self) -> int:
        if self._dim is None:
            self._load()
        assert self._dim is not None
        return self._dim

    def encode(self, texts: list[str]) -> np.ndarray:
        """Encode a list of texts to a (len, dim) float32 normalized array."""
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        model = self._load()
        vecs = model.encode(
            texts,
            batch_size=self.BATCH,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return vecs.astype(np.float32, copy=False)


class FakeEmbedder:
    """Deterministic fake embedder for tests.

    Maps each input string → a fixed-dim float32 vector derived from its
    SHA-256 digest. Vectors are L2-normalized so cosine distances behave.
    """

    def __init__(self, dim: int = 384) -> None:
        self._dim = dim

    @property
    def dim(self) -> int:
        return self._dim

    def _vec(self, text: str) -> np.ndarray:
        # Stretch the digest deterministically across `dim` floats.
        out = np.empty(self._dim, dtype=np.float32)
        i = 0
        counter = 0
        while i < self._dim:
            digest = hashlib.sha256(f"{text}|{counter}".encode()).digest()
            for b in digest:
                if i >= self._dim:
                    break
                # Map byte [0,255] → float in [-1, 1].
                out[i] = (b - 127.5) / 127.5
                i += 1
            counter += 1
        # Normalize.
        norm = float(np.linalg.norm(out))
        if norm > 0:
            out /= norm
        return out

    def encode(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self._dim), dtype=np.float32)
        return np.stack([self._vec(t) for t in texts], axis=0)
