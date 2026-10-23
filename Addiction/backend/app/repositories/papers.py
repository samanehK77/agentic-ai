"""Paper metadata access. Only metadata columns are selected; there is no file path column at all."""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from db.models import Paper


def list_papers(db: Session, limit: int, offset: int) -> tuple[list[dict], int]:
    total = db.scalar(select(func.count()).select_from(Paper))
    query = (
        select(
            Paper.paper_id, Paper.title, Paper.document_type, Paper.publisher, Paper.publication_year,
            Paper.source_note, Paper.ingest_status, Paper.created_at,
        )
        .order_by(Paper.paper_id)
        .limit(limit)
        .offset(offset)
    )
    return [dict(row) for row in db.execute(query).mappings()], total
