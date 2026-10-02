"""
Saved Searches API routes — /api/v1/saved-searches
"""

import uuid
import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ai.model_adapter import get_model_adapter, ModelAdapter
from app.core.orchestrator import run_search
from app.core.policy import check_rate_limit, get_current_user
from app.database import get_db
from app.models.saved_search import SavedSearch
from app.schemas.saved_search import SavedSearchCreate, SavedSearchOut, SavedSearchUpdate
from app.schemas.search import SearchRequest, SearchResponse

logger = structlog.get_logger(__name__)
router = APIRouter()


@router.post(
    "",
    response_model=SavedSearchOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a saved search query",
)
async def create_saved_search(
    payload: SavedSearchCreate,
    db: AsyncSession = Depends(get_db),
    user_id: str | None = Depends(get_current_user),
) -> SavedSearchOut:
    query_data = payload.query.model_dump() if isinstance(payload.query, SearchRequest) else payload.query

    effective_user_id = payload.user_id or user_id

    saved = SavedSearch(
        label=payload.label.strip(),
        query_json=query_data,
        user_id=effective_user_id,
    )
    db.add(saved)
    await db.commit()
    await db.refresh(saved)
    logger.info("saved_search.created", id=str(saved.id), label=saved.label, user_id=effective_user_id)
    return saved


@router.get(
    "",
    response_model=list[SavedSearchOut],
    summary="List saved searches",
)
async def list_saved_searches(
    user_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    auth_user_id: str | None = Depends(get_current_user),
) -> list[SavedSearchOut]:
    filter_user = user_id or auth_user_id
    query = select(SavedSearch).order_by(desc(SavedSearch.created_at))
    if filter_user:
        query = query.where(SavedSearch.user_id == filter_user)

    result = await db.execute(query)
    searches = result.scalars().all()
    return list(searches)


@router.get(
    "/{saved_search_id}",
    response_model=SavedSearchOut,
    summary="Get a saved search by ID",
)
async def get_saved_search(
    saved_search_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> SavedSearchOut:
    saved = await db.get(SavedSearch, saved_search_id)
    if not saved:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Saved search {saved_search_id} not found",
        )
    return saved


@router.patch(
    "/{saved_search_id}",
    response_model=SavedSearchOut,
    summary="Update a saved search",
)
async def update_saved_search(
    saved_search_id: uuid.UUID,
    payload: SavedSearchUpdate,
    db: AsyncSession = Depends(get_db),
) -> SavedSearchOut:
    saved = await db.get(SavedSearch, saved_search_id)
    if not saved:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Saved search {saved_search_id} not found",
        )

    if payload.label is not None:
        saved.label = payload.label.strip()
    if payload.query is not None:
        saved.query_json = (
            payload.query.model_dump()
            if isinstance(payload.query, SearchRequest)
            else payload.query
        )

    await db.commit()
    await db.refresh(saved)
    logger.info("saved_search.updated", id=str(saved.id))
    return saved


@router.delete(
    "/{saved_search_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a saved search",
)
async def delete_saved_search(
    saved_search_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    saved = await db.get(SavedSearch, saved_search_id)
    if not saved:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Saved search {saved_search_id} not found",
        )
    await db.delete(saved)
    await db.commit()
    logger.info("saved_search.deleted", id=str(saved_search_id))


@router.post(
    "/{saved_search_id}/execute",
    response_model=SearchResponse,
    summary="Execute a saved search",
)
async def execute_saved_search(
    saved_search_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    adapter: ModelAdapter = Depends(get_model_adapter),
    user_id: str | None = Depends(get_current_user),
    _: None = Depends(check_rate_limit),
) -> SearchResponse:
    saved = await db.get(SavedSearch, saved_search_id)
    if not saved:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Saved search {saved_search_id} not found",
        )

    request = SearchRequest(**saved.query_json)
    return await run_search(request=request, db=db, adapter=adapter, user_id=user_id)
