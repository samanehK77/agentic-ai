// Turns API JSON into the shapes the UI already uses (see docs/FRONTEND_INTEGRATION_PLAN.md).
// Pure functions: no network, no DOM.

const GENDER_LABELS = { woman: "Woman", man: "Man", non_binary: "Non-binary", other: "Other", unknown: "Unknown" };
const CATEGORY_LABELS = { alcohol: "Alcohol", cannabis: "Cannabis", opioids: "Opioids", stimulants: "Stimulants" };
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

const words = (value) => {
  const text = String(value).replaceAll("_", " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
};

export function categoryLabel(primaryCategory, subject) {
  if (primaryCategory === "behavioral") return `Behavioral: ${subject || "unknown"}`;
  return CATEGORY_LABELS[primaryCategory] || words(primaryCategory);
}

// "2012-09-01" + precision -> "2012" | "Sep 2012" | "1 Sep 2012". Parsed by hand to avoid time-zone shifts.
export function formatDate(isoDate, precision = "day") {
  const [year, month, day] = isoDate.split("-").map(Number);
  if (precision === "year") return String(year);
  if (precision === "month") return `${MONTHS[month - 1]} ${year}`;
  return `${day} ${MONTHS[month - 1]} ${year}`;
}

export function patientListItem(api) {
  return {
    id: api.patient_id,
    age: api.age_at_intake,
    sex: GENDER_LABELS[api.gender] || words(api.gender),
    category: categoryLabel(api.primary_category, api.primary_use_subject),
    summary: api.history_summary,
    treatment_summary: api.treatment_summary,
  };
}

export function patientDetail(profile, historyItems) {
  const latest = [...profile.progress].sort((a, b) => a.observed_on.localeCompare(b.observed_on)).at(-1);
  const factors = (kind) => profile.factors.filter((f) => f.kind === kind).map((f) => f.description);

  return {
    ...patientListItem(profile),
    background: profile.background,
    behaviors: factors("observed_behavior"),
    history: historyItems
      .filter((item) => item.source === "history")
      .map((item) => ({ period: formatDate(item.event_date, item.date_precision || "day"), event: item.summary })),
    triggers: factors("trigger"),
    previous_interventions: profile.interventions.map((i) => ({
      name: `${words(i.type)} (${i.setting})`,
      period: `${formatDate(i.start_date)} to ${i.end_date ? formatDate(i.end_date) : "ongoing"}`,
      outcome: i.reported_outcome,
    })),
    progress: latest
      ? { status: `${words(latest.use_status)}, motivation: ${latest.motivation.replaceAll("_", " ")}`, note: latest.note }
      : { status: "No observations recorded", note: "" },
  };
}

// One hit of POST /api/retrieval/search -> the shape the Evidence Inspector uses.
// citation_id is the real chunk id, so a citation can only ever point to a retrieved chunk.
export function evidenceChunk(hit) {
  const pages = hit.page_start === hit.page_end ? String(hit.page_start) : `${hit.page_start}-${hit.page_end}`;
  return {
    citation_id: hit.chunk_id,
    document: hit.title,
    section: hit.section_title || "(no section title)",
    page: pages,
    text: hit.text,
    score: hit.similarity, // cosine similarity: a score, not a probability
    section_type: hit.section_type,
    possible_injection: hit.possible_injection === true,
    real: true,
  };
}

// ---------------------------------------------------------------- Batch 07: answers

// API mode names <-> the UI's short names.
export const API_MODE = { gk: "general_knowledge", rag: "rag", both: "both" };
export const UI_MODE = { general_knowledge: "gk", rag: "rag", both: "both" };

// The Evidence Inspector list for one answer: every chunk shown to the model, with whether it was cited.
export function evidenceFromAnswer(answer) {
  const quoteFor = new Map(answer.citations.map((c) => [c.chunk_id, { quote: c.quote, verified: c.verified }]));
  return answer.evidence.map((e) => {
    const pages = e.page_start == null ? "?" : e.page_start === e.page_end ? String(e.page_start) : `${e.page_start}-${e.page_end}`;
    return {
      citation_id: e.chunk_id,
      document: e.source_title || "(document no longer available)",
      section: e.section_title || "(no section title)",
      page: pages,
      text: e.text,
      score: e.similarity,
      section_type: e.section_type,
      possible_injection: e.possible_injection === true,
      real: true,
      alias: e.alias,
      cited: e.cited === true,
      excluded_reason: e.excluded_reason,
      stale: e.stale === true,
      quote: quoteFor.get(e.chunk_id)?.quote ?? null,
      quote_verified: quoteFor.get(e.chunk_id)?.verified ?? null,
    };
  });
}

const NODE_LABELS = {
  validate_inputs: "Validate input",
  safety_screen: "Safety screen",
  classify_intent: "Classify question",
  decide_retrieval: "Decide retrieval",
  execute_retrieval: "Search documents",
  assess_evidence: "Assess evidence",
  generate_answer: "Generate answer",
  validate_citations: "Check citations",
  safety_check: "Safety check",
  format_output: "Assemble response",
};

const humanize = (code) => String(code || "").replaceAll("_", " ");

// One line of detail per workflow node. Every value comes from the backend's statistics-only trace (no question or chunk text).
function nodeDetail(evt, answer) {
  if (evt.status === "skipped") return `skipped: ${evt.reason || humanize(evt.reason_code)}`;
  const counts = evt.counts || {};
  const parts = [];
  switch (evt.node) {
    case "classify_intent":
      parts.push(humanize(answer.classification?.label || evt.reason_code));
      if (evt.status === "ended") parts.push(humanize(evt.reason_code));
      break;
    case "execute_retrieval":
      parts.push(`${counts.chunks ?? 0} chunk(s)`);
      break;
    case "assess_evidence": {
      const level = answer.evidence_assessment?.level;
      parts.push(evt.status === "ended" ? "evidence insufficient: no model call" : `evidence ${level || "checked"}`);
      if (evt.reason_code === "insufficient_retry_follow_up") parts.push("searching again with the previous question");
      break;
    }
    case "generate_answer":
      parts.push(`${counts.prompt_tokens ?? 0} prompt / ${counts.completion_tokens ?? 0} completion tokens`);
      break;
    case "validate_citations":
      parts.push(`${counts.verified ?? 0} of ${counts.citations ?? 0} quote(s) verified`, `${counts.unsupported_claims ?? 0} unsupported claim(s)`);
      break;
    default:
      if (evt.reason) parts.push(evt.reason);
  }
  if (evt.duration_ms != null) parts.push(`${evt.duration_ms} ms`);
  return parts.filter(Boolean).join(" · ");
}

// Execution trace of the answer workflow (Batch 08) -> timeline items: a summary line, then one item per node
// (nodes that did not run are shown as skipped, with the reason).
function workflowToEvents(answer, patientId) {
  const trace = answer.execution_trace;
  const total = trace.reduce((sum, evt) => sum + (evt.duration_ms || 0), 0);
  const route = answer.retrieval_decision
    ? (answer.retrieval_decision.needed ? "documents searched" : "documents not searched")
    : "ended before retrieval";
  const items = [{
    id: `evt-${answer.message_id}-summary`,
    type: "info",
    status: "ok",
    label: "Answer workflow",
    detail: [humanize(answer.classification?.label), route, `${total} ms in the workflow`].filter(Boolean).join(" · "),
    time: new Date(Date.parse(answer.created_at) || Date.now()).toISOString(),
    patient_id: patientId,
  }];
  trace.forEach((evt, i) => items.push({
    id: `evt-${answer.message_id}-${i}`,
    type: evt.node === "execute_retrieval" ? "retrieval" : evt.node === "generate_answer" ? "generation" : "info",
    status: evt.status,
    label: NODE_LABELS[evt.node] || evt.node,
    detail: nodeDetail(evt, answer),
    time: evt.started_at || new Date(Date.parse(answer.created_at) || Date.now()).toISOString(),
    patient_id: patientId,
  }));
  return items;
}

// Trace events of an answer -> timeline items (validation and safety use the generic "info" icon). Answers stored before
// Batch 08 have no execution trace and keep the short Batch 07 list.
export function traceToEvents(answer, patientId) {
  if (Array.isArray(answer.execution_trace) && answer.execution_trace.length) return workflowToEvents(answer, patientId);
  const base = Date.parse(answer.created_at) || Date.now();
  return answer.trace.map((evt, i) => ({
    id: `evt-${answer.message_id}-${i}`,
    type: evt.type === "retrieval" || evt.type === "generation" ? evt.type : "info",
    label: evt.label,
    detail: [evt.detail, evt.latency_ms != null ? `${evt.latency_ms} ms` : ""].filter(Boolean).join(" · "),
    time: new Date(base + i * 50).toISOString(),
    patient_id: patientId,
  }));
}

// A stored API message -> the chat message shape the renderers use.
export function messageFromApi(item) {
  if (item.role === "user") return { role: "user", text: item.content };
  const mode = UI_MODE[item.mode] || "rag";
  if (!item.answer) return { role: "assistant", text: item.content, mode, kind: "plain" };
  return { role: "assistant", text: item.content, mode, kind: "answer", answer: item.answer };
}

// ---------------------------------------------------------------- Batch 09: the audit timeline

// Plain-language help for the error codes the API can record (the codes themselves are stable).
export const ERROR_DIAGNOSIS = {
  llm_timeout: "The language model did not answer in time. A local model can be slow: try again, or check that the model server is running.",
  llm_unavailable: "The model server could not be reached, or it is busy with another question. Check that it is running (for Ollama: ollama serve).",
  llm_bad_output: "The model replied, but not in the required format, even after one repair attempt. Small local models do this sometimes: ask again.",
  llm_not_configured: "No language model is configured on the server.",
  workflow_timeout: "A step of the answer workflow ran out of time. Try again; a very slow model or search is the usual cause.",
  rate_limited: "Too many questions in a short time. Wait a moment and try again.",
  retrieval_unavailable: "Document search is not available (the embedding model is not installed or could not load).",
  retrieval_not_ready: "No document chunks have been embedded yet (run: python -m app.embedding).",
  index_incompatible: "The stored embeddings come from a different model: re-run python -m app.embedding --force.",
  idempotency_conflict: "The same request key was used for a different question.",
  service_unavailable: "The database was not reachable.",
  internal_error: "An unexpected error happened on the server. The request id in the server log helps to find it.",
};

export const OUTCOME_TEXT = {
  answered: "Answered", no_evidence: "No evidence", unsupported: "Not supported", crisis: "Safety notice",
  replayed: "Replayed", error: "Failed", running: "Running…", interrupted: "Interrupted", ok: "Done", denied: "Refused",
};

const EVENT_LABELS = {
  question_submitted: "Question submitted", node_executed: "Workflow step", retrieval_executed: "Documents searched",
  llm_request: "Model request", citation_validated: "Citations checked", answer_returned: "Answer returned",
  pipeline_error: "Run failed", access_denied: "Access refused", feedback_submitted: "Feedback", session_created: "Conversation started",
  patient_viewed: "Patient opened", sign_in_succeeded: "Signed in", sign_in_failed: "Sign-in failed", sign_out: "Signed out",
};

const join = (parts) => parts.filter((p) => p !== null && p !== undefined && p !== "").join(" · ");

// One audit event -> { label, status, detail, chunks, badge }. Every value is a code, a count or an id (never question or chunk text).
export function auditEventView(evt) {
  const m = evt.metadata || {};
  const view = { id: evt.event_id, type: evt.event_type, label: EVENT_LABELS[evt.event_type] || humanize(evt.event_type),
    status: evt.outcome, latency: evt.latency_ms, detail: "", chunks: [], badge: null, time: evt.occurred_at };
  switch (evt.event_type) {
    case "node_executed":
      view.label = NODE_LABELS[m.node] || humanize(m.node);
      view.status = m.status === "ok" ? "ok" : m.status;
      view.detail = m.status === "skipped" ? `skipped: ${humanize(m.reason_code)}` : humanize(m.reason_code);
      break;
    case "question_submitted":
      view.detail = join([m.mode && `mode ${m.mode}`, m.question_chars != null && `${m.question_chars} characters`]);
      break;
    case "retrieval_executed":
      view.detail = join([`attempt ${m.attempt}`, `top_k ${m.top_k ?? "?"}`, `threshold ${m.threshold ?? "none"}`, `${m.chunks} chunk(s)`,
        m.evidence_level && `evidence ${m.evidence_level}`]);
      view.chunks = m.chunk_ids || [];
      break;
    case "llm_request":
      view.detail = join([m.model, `${m.prompt_tokens} prompt / ${m.completion_tokens} completion tokens`,
        m.retries ? `${m.retries} retry(ies)` : null, m.repair_attempted ? "repair attempted" : null]);
      break;
    case "citation_validated":
      view.detail = join([`${m.unsupported_claims} unsupported claim(s)`, `${m.sections} section(s)`]);
      view.badge = { text: `${m.verified} of ${m.citations} quotes verified`, ok: m.verified === m.citations };
      break;
    case "answer_returned":
      view.detail = m.replayed ? "stored answer replayed (no new run)" : join([OUTCOME_TEXT[m.result] || m.result, m.llm_called ? "model used" : "no model call"]);
      break;
    case "pipeline_error":
      view.detail = join([evt.error_code, m.failed_node && `at ${humanize(m.failed_node)}`]);
      break;
    case "access_denied":
      view.detail = `${humanize(m.reason_code)} (${m.route})`;
      break;
    case "feedback_submitted":
      view.detail = join([humanize(m.rating), m.reason && humanize(m.reason)]);
      break;
    default:
      view.detail = join([m.patient_id, m.role, m.reason && humanize(m.reason)]);
  }
  if (evt.outcome === "error" && evt.error_code && !view.detail.includes(evt.error_code)) view.detail = join([view.detail, evt.error_code]);
  return view;
}

// One correlation group -> what the timeline shows.
export function auditGroupView(group) {
  const events = group.events.map(auditEventView);
  return {
    id: group.correlation_id,
    shortId: group.correlation_id.slice(0, 8),
    kind: group.kind,
    outcome: group.outcome,
    outcomeText: OUTCOME_TEXT[group.outcome] || humanize(group.outcome),
    errorCode: group.error_code,
    diagnosis: group.error_code ? (ERROR_DIAGNOSIS[group.error_code] || "See the error code in docs/OBSERVABILITY.md.") : null,
    totalMs: group.total_latency_ms,
    startedAt: group.started_at,
    config: group.config,
    events,
    title: group.kind === "question" ? "Question" : (events[0]?.label || "Action"),
  };
}
