"""Audit logging (Batch 09): an append-only record of who did what and how it went, as metadata only.
See docs/OBSERVABILITY.md."""
from app.audit.service import AuditService

__all__ = ["AuditService"]
