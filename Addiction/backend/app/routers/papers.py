from fastapi import APIRouter

from app import services
from app.deps import DbSession, PageParams
from app.schemas.common import ERROR_422, Page
from app.schemas.papers import PaperOut

router = APIRouter(prefix="/api/papers", tags=["papers"])


@router.get(
    "",
    response_model=Page[PaperOut],
    summary="List research papers (metadata only)",
    description="Metadata for the research corpus. Document text and chunks are not available yet (Batch 05), "
                "and no file paths are exposed.",
    responses=ERROR_422,
)
def list_papers(db: DbSession, page: PageParams) -> Page[PaperOut]:
    items, total = services.list_papers(db, page.limit, page.offset)
    return Page[PaperOut](items=items, total=total, limit=page.limit, offset=page.offset)
