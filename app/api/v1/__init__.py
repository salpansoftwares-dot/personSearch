from fastapi import APIRouter

from app.api.v1 import disputes, persons, search

router = APIRouter()
router.include_router(search.router, tags=["search"])
router.include_router(persons.router, prefix="/persons", tags=["persons"])
router.include_router(disputes.router, prefix="/disputes", tags=["disputes"])
