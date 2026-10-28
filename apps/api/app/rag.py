"""Permission-filtered hybrid search: PostgreSQL full text + pgvector reciprocal-rank fusion."""
import math
import re

from fastapi import APIRouter, Depends
from openai import AsyncOpenAI
from pgvector.sqlalchemy import Vector
from pydantic import BaseModel, Field
from sqlalchemy import cast, func, select
from sqlalchemy.orm import Session

from app.auth import Principal, authorize_department, get_principal, principal_for_user
from app.core.config import get_settings
from app.db import get_db
from app.documents import document_filter
from app.models import Document, DocumentChunk, EmbeddingRecord
from app.providers import ProviderError, ProviderResult, finalize_usage, price, reserve_usage

router = APIRouter(tags=["retrieval"])


async def embeddings(db, p, department_id, texts: list[str]) -> list[list[float]]:
    s = get_settings()
    if not s.openai_api_key:
        raise ProviderError("embedding_not_configured", "An OpenAI embedding key is required for semantic search")
    # Schema dimension fixed in migrations; changing models requires a reindex with compatible dimensions.
    if s.embedding_dimensions != 1536:
        raise ProviderError("embedding_dimensions", "This index requires 1536-dimensional embeddings")
    usage = reserve_usage(db, p, department_id, [{"role": "user", "content": t} for t in texts], "openai", s.embedding_model, max_tokens=1)
    try:
        result = await AsyncOpenAI(api_key=s.openai_api_key, timeout=s.model_timeout_seconds, max_retries=2).embeddings.create(model=s.embedding_model, input=texts, dimensions=1536)
        vectors = [item.embedding for item in sorted(result.data, key=lambda item: item.index)]
        if len(vectors) != len(texts) or any(len(v) != 1536 or not all(math.isfinite(n) for n in v) for v in vectors):
            raise ValueError("Invalid embeddings")
        finalize_usage(db, usage, ProviderResult("", "openai", s.embedding_model, result.usage.total_tokens, 0, price(result.usage.total_tokens, 0)))
        return vectors
    except Exception as exc:
        finalize_usage(db, usage, None)
        raise ProviderError("embedding_failed", "Embedding generation failed") from exc


def lexical_score(query: str, content: str) -> float:
    terms = set(re.findall(r"\w+", query.lower())) - {"the", "is", "what", "a", "an", "of", "to", "for", "and", "how", "does"}
    words = re.findall(r"\w+", content.lower())
    return sum(words.count(t) for t in terms) / max(1, math.sqrt(len(words)))


async def search(db: Session, p: Principal, query: str, department_id: str, limit: int = 5,
                 *, offline: bool = False, retrieval_info: dict | None = None) -> list[dict]:
    authorize_department(p, department_id, "documents:read")
    limit = max(1, min(limit, 20))
    query = query[:2000]
    base = select(DocumentChunk, Document).join(Document, DocumentChunk.document_id == Document.id).where(document_filter(p), Document.department_id == department_id, Document.status == "ready", DocumentChunk.version == Document.version)
    postgres = db.bind is not None and db.bind.dialect.name == "postgresql"
    if postgres:
        textsearch = func.to_tsvector("english", DocumentChunk.content)
        tsquery = func.plainto_tsquery("english", query)
        lexical = list(db.execute(base.where(textsearch.op("@@")(tsquery)).order_by(func.ts_rank_cd(textsearch, tsquery).desc()).limit(50)))
    else:
        # SQLite supports isolated tests/local no-service mode; it never simulates vectors.
        candidates = list(db.execute(base.limit(5000)))
        lexical = sorted((row for row in candidates if lexical_score(query, row[0].content) > 0), key=lambda row: lexical_score(query, row[0].content), reverse=True)[:50]
    rankings = [lexical]
    if retrieval_info is not None:
        retrieval_info["mode"] = "lexical"
    has_vectors = db.scalar(select(EmbeddingRecord.chunk_id).join(DocumentChunk).join(Document).where(document_filter(p), Document.department_id == department_id, Document.status == "ready", EmbeddingRecord.model == get_settings().embedding_model).limit(1))
    if not offline and postgres and has_vectors and get_settings().openai_api_key:
        vector = (await embeddings(db, p, department_id, [query]))[0]
        if postgres:
            distance = cast(EmbeddingRecord.vector, Vector(1536)).cosine_distance(vector)
            rankings.append(list(db.execute(base.join(EmbeddingRecord, EmbeddingRecord.chunk_id == DocumentChunk.id).where(EmbeddingRecord.model == get_settings().embedding_model, distance < 0.75).order_by(distance).limit(50))))
            if retrieval_info is not None:
                retrieval_info["mode"] = "hybrid"
    scores: dict[str, float] = {}
    rows: dict[str, tuple[DocumentChunk, Document]] = {}
    for ranking in rankings:
        for rank, row in enumerate(ranking):
            chunk, document = row
            scores[chunk.id] = scores.get(chunk.id, 0) + 1 / (60 + rank + 1)
            rows[chunk.id] = (chunk, document)
    keys = sorted(scores, key=lambda k: scores[k], reverse=True)[:max(limit, 20)]
    if not offline and get_settings().rerank_model and keys:
        from sentence_transformers import CrossEncoder
        reranker = CrossEncoder(get_settings().rerank_model, trust_remote_code=False)
        scores2 = reranker.predict([(query, rows[k][0].content) for k in keys])
        keys = [k for _, k in sorted(zip(scores2, keys), reverse=True)]
    # Embeddings/reranking may take seconds. Re-fetch selected chunks using the
    # user's current roles and ACLs before returning any cached source content.
    p = principal_for_user(db, p.id)
    authorize_department(p, department_id, "documents:read")
    authorized = db.execute(select(DocumentChunk, Document).join(Document).where(
        DocumentChunk.id.in_(keys), document_filter(p), Document.department_id == department_id,
        Document.status == "ready", DocumentChunk.version == Document.version)
        .execution_options(populate_existing=True)).all()
    rows = {chunk.id: (chunk, document) for chunk, document in authorized}
    keys = [key for key in keys if key in rows]
    return [{"document_id": rows[k][1].id, "document_name": rows[k][1].name,
             "document_version": rows[k][1].version, "chunk_id": k,
             "location": rows[k][0].location, "excerpt": rows[k][0].content,
             "score": scores[k]} for k in keys[:limit]]


class SearchInput(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    department_id: str
    limit: int = Field(default=5, ge=1, le=20)


@router.post("/search")
async def search_endpoint(body: SearchInput, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    info: dict = {}
    items = await search(db, p, body.query, body.department_id, body.limit, retrieval_info=info)
    return {"items": items, "mode": info["mode"], "total": len(items)}
