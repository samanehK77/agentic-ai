"""Quality report: statistics only. No document text ever goes into the report or the run record."""
import json
from datetime import timezone
from pathlib import Path

from app.ingestion.config import IngestConfig
from app.ingestion.runner import RunOutcome


def document_entry(result) -> dict:
    stored = getattr(result, "stored", None)
    if stored:  # unchanged: statistics come from the database
        tokens = {"min": stored["tmin"] or 0, "median": stored["tmed"] or 0, "max": stored["tmax"] or 0}
        chunks, injection = stored["chunks"], stored["injection"]
        section_types = {k: stored["section_types"].get(k, 0) for k in ("body", "table_or_figure", "references", "front_matter")}
        characters = headers = leaders = None
    else:
        tokens, chunks = result.token_stats(), len(result.chunks)
        injection, section_types = sum(result.injection_flags), result.section_counts()
        characters, headers, leaders = result.characters, result.headers_footers_removed, result.leader_lines_removed
    return {
        "paper_id": result.paper_id, "status": result.status, "action": result.action, "reason": result.reason,
        "pages": result.page_count, "low_text_pages": len(result.low_text_pages),
        "low_text_page_numbers": result.low_text_pages, "characters": characters,
        "headers_footers_removed": headers, "toc_leader_lines_removed": leaders,
        "chunks": chunks, "tokens": tokens, "section_types": section_types, "possible_injection": injection,
    }


def build_report(outcome: RunOutcome, config: IngestConfig, dry_run: bool) -> dict:
    documents = [document_entry(r) for r in outcome.results]
    return {
        "run_id": outcome.run_id, "dry_run": dry_run,
        "started_at": outcome.started_at.astimezone(timezone.utc).isoformat() if outcome.started_at else None,
        "finished_at": outcome.finished_at.astimezone(timezone.utc).isoformat() if outcome.finished_at else None,
        "config": config.public_summary(), "unregistered_pdfs": len(outcome.unregistered),
        "documents": documents,
        "totals": {
            "documents": len(documents), "chunks": sum(d["chunks"] for d in documents),
            "failed": sum(d["status"] == "failed" for d in documents),
            "needs_ocr": sum(d["status"] == "needs_ocr" for d in documents),
            "unchanged": sum(d["action"] == "unchanged" for d in documents),
        },
    }


def write_report(report: dict, report_dir: Path) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = (report["started_at"] or "run").replace(":", "").replace("-", "").split(".")[0].replace("+0000", "Z")
    name = f"ingestion-{'dryrun-' if report['dry_run'] else ''}{stamp}.json"
    path = report_dir / name
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path
