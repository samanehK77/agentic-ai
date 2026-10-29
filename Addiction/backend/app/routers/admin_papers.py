"""Read-only administrator endpoints for the ingestion results. Ingestion itself is a command-line job (see docs/INGESTION.md)."""
from typing import Annotated, Literal

from fastapi import APIRouter, Path, Query

from app import services
from app.deps import DbSession, PageParams
from app.schemas.admin_papers import AdminPaperDetail, AdminPaperOut, ChunkOut
from app.schemas.common import ERROR_403, ERROR_404, ERROR_422, Page
from db.models import VOCAB

router = APIRouter(prefix="/api/admin", tags=["admin"])

PaperIdPath = Annotated[str, Path(pattern=r"^[a-z0-9][a-z0-9-]{0,99}$", examples=["who-mhgap-guideline-2023"])]
ChunkIdPath = Annotated[str, Path(pattern=r"^[a-z0-9][a-z0-9-]{0,99}-c[0-9]{4,}$", examples=["who-mhgap-guideline-2023-c0042"])]
SectionType = Literal[*VOCAB["section_type"]]


@router.get(
    "/papers",
    response_model=Page[AdminPaperOut],
    summary="List papers with ingestion status (admin)",
    description="Administrators only. Ingestion fields per paper; no file names, paths or file hashes.",
    responses={**ERROR_403, **ERROR_422},
)
def list_papers(db: DbSession, page: PageParams) -> Page[AdminPaperOut]:
    items, total = services.admin_list_papers(db, page.limit, page.offset)
    return Page[AdminPaperOut](items=items, total=total, limit=page.limit, offset=page.offset)


@router.get(
    "/papers/{paper_id}",
    response_model=AdminPaperDetail,
    summary="One paper with ingestion details (admin)",
    responses={**ERROR_403, **ERROR_404, **ERROR_422},
)
def get_paper(paper_id: PaperIdPath, db: DbSession) -> AdminPaperDetail:
    return AdminPaperDetail(**services.admin_get_paper(db, paper_id))


@router.get(
    "/papers/{paper_id}/chunks",
    response_model=Page[ChunkOut],
    summary="List the chunks of a paper (admin)",
    description="Administrators only: the response contains the full chunk text, which is copyrighted source material.",
    responses={**ERROR_403, **ERROR_404, **ERROR_422},
)
def list_chunks(
    paper_id: PaperIdPath, db: DbSession, page: PageParams,
    section_type: Annotated[SectionType | None, Query(description="Only chunks of this section type.")] = None,
) -> Page[ChunkOut]:
    items, total = services.admin_list_chunks(db, paper_id, section_type, page.limit, page.offset)
    return Page[ChunkOut](items=items, total=total, limit=page.limit, offset=page.offset)


@router.get(
    "/chunks/{chunk_id}",
    response_model=ChunkOut,
    summary="One chunk with its full text (admin)",
    responses={**ERROR_403, **ERROR_404, **ERROR_422},
)
def get_chunk(chunk_id: ChunkIdPath, db: DbSession) -> ChunkOut:
    return ChunkOut(**services.admin_get_chunk(db, chunk_id))
