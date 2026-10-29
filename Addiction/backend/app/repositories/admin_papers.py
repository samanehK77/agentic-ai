"""Administrator reads of papers and chunks. Selects explicit columns only: file_name and content_sha256 are never read."""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from db.models import Paper, PaperChunk

CHUNK_COLUMNS = (
    PaperChunk.chunk_id, PaperChunk.paper_id, PaperChunk.ordinal, PaperChunk.text, PaperChunk.token_count,
    PaperChunk.page_start, PaperChunk.page_end, PaperChunk.section_title, PaperChunk.section_type,
    PaperChunk.possible_injection, PaperChunk.created_at,
)


def _paper_query():
    chunk_count = (select(func.count()).select_from(PaperChunk).where(PaperChunk.paper_id == Paper.paper_id)
                   .correlate(Paper).scalar_subquery())
    return select(
        Paper.paper_id, Paper.title, Paper.document_type, Paper.publisher, Paper.publication_year, Paper.doi,
        Paper.metadata_source, Paper.ingest_status, Paper.ingest_note, Paper.page_count,
        func.cardinality(Paper.low_text_pages).label("low_text_page_count"), chunk_count.label("chunk_count"),
        Paper.chunking_version, Paper.ingested_at,
    )


def list_papers(db: Session, limit: int, offset: int) -> tuple[list[dict], int]:
    total = db.scalar(select(func.count()).select_from(Paper))
    query = _paper_query().order_by(Paper.paper_id).limit(limit).offset(offset)
    return [dict(row) for row in db.execute(query).mappings()], total


def get_paper(db: Session, paper_id: str) -> dict | None:
    row = db.execute(_paper_query().where(Paper.paper_id == paper_id)).mappings().first()
    if row is None:
        return None
    pages = db.scalar(select(Paper.low_text_pages).where(Paper.paper_id == paper_id))
    kinds = dict(db.execute(
        select(PaperChunk.section_type, func.count()).where(PaperChunk.paper_id == paper_id)
        .group_by(PaperChunk.section_type)).all())
    return {**dict(row), "low_text_pages": list(pages or []), "chunks_by_section_type": kinds}


def paper_exists(db: Session, paper_id: str) -> bool:
    return db.scalar(select(func.count()).select_from(Paper).where(Paper.paper_id == paper_id)) > 0


def list_chunks(db: Session, paper_id: str, section_type: str | None, limit: int, offset: int) -> tuple[list[dict], int]:
    filters = [PaperChunk.paper_id == paper_id]
    if section_type:
        filters.append(PaperChunk.section_type == section_type)
    total = db.scalar(select(func.count()).select_from(PaperChunk).where(*filters))
    query = select(*CHUNK_COLUMNS).where(*filters).order_by(PaperChunk.ordinal).limit(limit).offset(offset)
    return [dict(row) for row in db.execute(query).mappings()], total


def get_chunk(db: Session, chunk_id: str) -> dict | None:
    row = db.execute(select(*CHUNK_COLUMNS).where(PaperChunk.chunk_id == chunk_id)).mappings().first()
    return dict(row) if row else None
