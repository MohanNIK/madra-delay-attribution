from __future__ import annotations

import re

from .models import EvidenceSpan


class KeywordRetriever:
    """Small local retriever for prototypes and tests.

    It is intentionally simple. Replace this with BM25, FAISS, Elasticsearch,
    pgvector, or a legal-case retrieval service when the corpus is ready.
    """

    def __init__(self, spans: list[EvidenceSpan] | None = None):
        self.spans = spans or []

    @classmethod
    def from_case_text(cls, text: str, *, max_chars: int = 450) -> "KeywordRetriever":
        chunks: list[EvidenceSpan] = []
        sentences = [item.strip() for item in re.split(r"(?<=[。！？.!?])\s*", text) if item.strip()]
        buffer = ""
        for sentence in sentences:
            if len(buffer) + len(sentence) > max_chars and buffer:
                chunks.append(EvidenceSpan(span_id=f"E{len(chunks) + 1}", text=buffer.strip(), source="case"))
                buffer = sentence
            else:
                buffer = f"{buffer} {sentence}".strip()
        if buffer:
            chunks.append(EvidenceSpan(span_id=f"E{len(chunks) + 1}", text=buffer.strip(), source="case"))
        return cls(chunks)

    def retrieve(self, query: str, *, top_k: int = 6) -> list[EvidenceSpan]:
        query_terms = self._terms(query)
        scored: list[tuple[int, EvidenceSpan]] = []
        for span in self.spans:
            span_terms = self._terms(span.text)
            score = len(query_terms & span_terms)
            scored.append((score, span))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [span for score, span in scored[:top_k] if score > 0] or self.spans[:top_k]

    @classmethod
    def from_case_record(cls, case) -> "KeywordRetriever":
        return cls(list(case.evidence_spans))

    @staticmethod
    def _terms(text: str) -> set[str]:
        return {term.lower() for term in re.findall(r"[A-Za-z0-9_\u4e00-\u9fff]+", text)}
