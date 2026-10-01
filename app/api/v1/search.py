"""
Search API routes  —  POST /api/v1/search
"""

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ai.model_adapter import get_model_adapter, ModelAdapter
from app.core.orchestrator import run_search
from app.core.policy import check_rate_limit, get_current_user
from app.database import get_db
from app.schemas.search import SearchRequest, SearchResponse

logger = structlog.get_logger(__name__)
router = APIRouter()


@router.post(
    "/search",
    response_model=SearchResponse,
    summary="Search for a person's professional profile",
    description=(
        "Returns sourced professional claims about the named person. "
        "Every claim is labelled 'possible match' and links to its evidence source. "
        "Requires a stated purpose for accountable use."
    ),
)
async def search(
    request: SearchRequest,
    db: AsyncSession = Depends(get_db),
    adapter: ModelAdapter = Depends(get_model_adapter),
    user_id: str | None = Depends(get_current_user),
    _: None = Depends(check_rate_limit),
) -> SearchResponse:
    return await run_search(request=request, db=db, adapter=adapter, user_id=user_id)
