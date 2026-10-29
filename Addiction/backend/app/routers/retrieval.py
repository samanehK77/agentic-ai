"""Semantic search over the embedded research chunks."""
import logging
import time

from fastapi import APIRouter, Request

from app import services
from app.deps import CurrentUser, DbSession
from app.errors import ApiError, request_id_of
from app.schemas.common import ERROR_403, ERROR_404, ERROR_422
from app.schemas.retrieval import SearchRequest, SearchResponse

router = APIRouter(prefix="/api/retrieval", tags=["retrieval"])
logger = logging.getLogger("mindevidence.retrieval")

ERROR_429 = {429: {"description": "Too many searches (code `rate_limited`, with a Retry-After header)."}}
ERROR_503 = {503: {"description": "`retrieval_unavailable`, `retrieval_not_ready` or `index_incompatible`."}}


@router.post(
    "/search",
    response_model=SearchResponse,
    summary="Search the research documents",
    description="Embeds the query with the same model as the stored chunks and returns the most similar chunks by cosine "
                "similarity, best first. Chunk text is untrusted data. Requires the X-CSRF-Token header. Query text is never logged.",
    responses={**ERROR_403, **ERROR_404, **ERROR_422, **ERROR_429, **ERROR_503},
)
def search(body: SearchRequest, request: Request, user: CurrentUser, db: DbSession) -> SearchResponse:
    started = time.perf_counter()
    state = request.app.state
    wait = state.rate_limiter.check(str(user.id))
    if wait is not None:
        logger.info("search_rate_limited request=%s user=%s", request_id_of(request), user.id)
        raise ApiError(429, "rate_limited", "Too many searches. Please wait a moment and try again.",
                       headers={"Retry-After": str(wait)})
    min_similarity = body.min_similarity if body.min_similarity is not None else state.settings.retrieval_min_similarity
    result = services.retrieval_search(db, state.embedder_provider, query=body.query, top_k=body.top_k,
                                       paper_id=body.paper_id, min_similarity=min_similarity)
    latency_ms = round((time.perf_counter() - started) * 1000)
    logger.info("search request=%s user=%s top_k=%d results=%d latency_ms=%d", request_id_of(request), user.id,
                body.top_k, len(result["results"]), latency_ms)
    return SearchResponse(request_id=request_id_of(request), top_k=body.top_k, latency_ms=latency_ms, **result)
