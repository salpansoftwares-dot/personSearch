from fastapi import APIRouter

from app.api.v1 import disputes, persons, saved_searches, search, suppressions

router = APIRouter()
router.include_router(search.router, tags=["search"])
router.include_router(saved_searches.router, prefix="/saved-searches", tags=["saved-searches"])
router.include_router(persons.router, prefix="/persons", tags=["persons"])
router.include_router(disputes.router, prefix="/disputes", tags=["disputes"])
router.include_router(suppressions.router, prefix="/suppressions", tags=["suppressions"])

