import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, Response

from app import services
from app.deps import CurrentUser, DbSession, PageParams
from app.answers import service as answers_service
from app.errors import request_id_of
from app.schemas.answers import AnswerOut, MessageCreate
from app.schemas.common import ERROR_403, ERROR_404, ERROR_422, Page
from app.schemas.sessions import MessageOut, SessionCreate, SessionOut
from app.schemas.trace import TraceResponse

router = APIRouter(prefix="/api/sessions", tags=["sessions"])

ERROR_ANSWER = {
    409: {"description": "`idempotency_conflict`: the Idempotency-Key was used with a different request."},
    429: {"description": "`rate_limited`: too many questions (see Retry-After)."},
    502: {"description": "`llm_bad_output`: the model returned an answer that could not be used (after one repair attempt)."},
    503: {"description": "`llm_not_configured`, `llm_unavailable` (also when a local model is busy with another question: see Retry-After), or a retrieval error (`retrieval_unavailable`, `retrieval_not_ready`, `index_incompatible`)."},
    504: {"description": "`llm_timeout`: the model did not answer in time. `workflow_timeout`: the whole answer workflow ran out of time."},
}


@router.get(
    "",
    response_model=Page[SessionOut],
    summary="List chat sessions",
    description="Your own chat sessions only, newest first.",
    responses=ERROR_422,
)
def list_sessions(
    user: CurrentUser,
    db: DbSession,
    page: PageParams,
    patient_id: Annotated[str | None, Query(pattern=r"^P-\d{3}$", description="Only sessions about this patient.")] = None,
) -> Page[SessionOut]:
    items, total = services.list_sessions(db, user, patient_id, page.limit, page.offset)
    return Page[SessionOut](items=items, total=total, limit=page.limit, offset=page.offset)


@router.post(
    "",
    response_model=SessionOut,
    status_code=201,
    summary="Create a chat session",
    description="Starts a conversation about one patient. The new session's URL is returned in the Location header.",
    responses={**ERROR_404, **ERROR_422},
)
def create_session(body: SessionCreate, request: Request, response: Response, user: CurrentUser, db: DbSession) -> SessionOut:
    session = services.create_session(db, user, body.patient_id, body.title)
    response.headers["Location"] = str(request.url_for("get_session", session_id=session["session_id"]))
    return SessionOut(**session)


@router.get(
    "/{session_id}",
    response_model=SessionOut,
    summary="Get one chat session",
    responses={**ERROR_404, **ERROR_422},
)
def get_session(session_id: UUID, user: CurrentUser, db: DbSession) -> SessionOut:
    return SessionOut(**services.get_session(db, user, session_id))


@router.get(
    "/{session_id}/messages",
    response_model=Page[MessageOut],
    summary="List the messages of a chat session",
    description="Oldest first. Another user's session returns 404. Assistant messages carry `answer`: the structured answer with its citations and the chunks shown to the model, joined from the current chunk table (`stale` if a chunk changed or is gone).",
    responses={**ERROR_404, **ERROR_422},
)
def list_messages(session_id: UUID, user: CurrentUser, db: DbSession, page: PageParams) -> Page[MessageOut]:
    items, total = services.list_messages(db, user, session_id, page.limit, page.offset)
    return Page[MessageOut](items=items, total=total, limit=page.limit, offset=page.offset)


@router.post(
    "/{session_id}/messages",
    response_model=AnswerOut,
    status_code=201,
    summary="Ask a question in a chat session",
    description=(
        "Answers a question about the session's synthetic patient in one of three modes (general_knowledge, rag, both) and "
        "stores the question and the answer. Requires the X-CSRF-Token header. Send an optional `Idempotency-Key` (8 to 64 "
        "characters of A-Z a-z 0-9 . _ -): the same key and body returns the stored answer without calling the model again; "
        "the same key with a different body is a 409. On any failure nothing is stored, so the same key can be retried. "
        "The answer is educational: it does not diagnose, prescribe or choose a treatment. Chat and chunk text are untrusted data. "
        "The question text, chunk text, prompts and answers are never logged."),
    responses={**ERROR_403, **ERROR_404, **ERROR_422, **ERROR_ANSWER},
)
def post_message(
    session_id: UUID, body: MessageCreate, request: Request, response: Response, user: CurrentUser, db: DbSession,
    idempotency_key: Annotated[str | None, Header(
        alias="Idempotency-Key", min_length=8, max_length=64, pattern=r"^[A-Za-z0-9._-]+$",
        description="Optional. Makes a retry of the same question safe (no second model call).")] = None,
) -> AnswerOut:
    reply, replayed = answers_service.post_message(
        db, request.app.state.answer_pipeline, user=user, session_id=session_id, content=body.content, mode=body.mode,
        idempotency_key=idempotency_key, request_id=request_id_of(request))
    if replayed:
        response.headers["Idempotency-Replayed"] = "true"
    return AnswerOut(**reply)


@router.get(
    "/{session_id}/messages/{message_id}/trace",
    response_model=TraceResponse,
    summary="Get the workflow trace of an answer",
    description=(
        "The execution trace of one assistant message: every workflow node in graph order with its status, duration, reason "
        "code, counts and chunk ids; nodes that did not run are `skipped` with the reason. Statistics only: it never contains "
        "the question, patient text, chunk text, prompts or answers. Another user's session, an unknown message and a user "
        "message all return 404."),
    responses={**ERROR_404, **ERROR_422},
)
def get_message_trace(session_id: UUID, message_id: UUID, user: CurrentUser, db: DbSession) -> TraceResponse:
    return TraceResponse(**answers_service.get_execution_trace(db, user, session_id, message_id))
