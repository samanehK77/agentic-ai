// Entry point: loads data through api.js, updates the store, re-renders panels.
import * as api from "./api.js";
import { state, setState, subscribe, addMessage } from "./state.js";
import { MODES } from "../data/mock-data.js";
import { API_MODE, evidenceFromAnswer, messageFromApi } from "./adapters.js";
import { renderAuth } from "./render/auth.js";
import { renderPatients } from "./render/patients.js";
import { renderPatientDetail } from "./render/patientDetail.js";
import { renderChat, updateChatStatus } from "./render/chat.js";
import { renderEvidence } from "./render/evidence.js";
import { renderTimeline } from "./render/timeline.js";
import { renderMode } from "./render/modeIndicator.js";
import { icon, PROVENANCE } from "./render/dom.js";

// Bumped whenever the demo state changes, so responses from old requests are ignored.
let epoch = 0;

const errorText = (err) => (err instanceof Error ? err.message : String(err));

// Clear messages for the errors the answer endpoint can return (the API's own text is kept for anything else).
const FRIENDLY = {
  rate_limited: "You are asking questions too quickly. Please wait a moment and try again.",
  llm_not_configured: "The language model is not configured on this server, so answers are not available. Ask the administrator.",
  llm_unavailable: "The language model service is not available right now. Please try again in a little while.",
  llm_timeout: "The language model took too long to answer. Please try again.",
  workflow_timeout: "Preparing the answer took too long. Please try again.",
  client_timeout: "The answer took longer than the browser waits. The server may still be working: try again in a minute.",
  llm_bad_output: "The language model returned an answer that could not be used. Please try asking again.",
  retrieval_unavailable: "Document search is not available on this server (the embedding model is not installed).",
  retrieval_not_ready: "The documents have not been embedded yet. Run: python -m app.embedding",
  index_incompatible: "The stored document index was made with a different model. Re-run: python -m app.embedding --force",
  idempotency_conflict: "That request was already used for a different question. Please ask again.",
};
function friendlyText(err) {
  if (!(err instanceof api.ApiError)) return errorText(err);
  // A local model serves one question at a time: say so, and say when to try again.
  const busy = err.code === "llm_unavailable" && /busy/i.test(err.message);
  const base = busy
    ? "The model is busy answering another question."
    : FRIENDLY[err.code] || errorText(err);
  const hint = (busy || err.status === 429 || err.status === 503) && err.retryAfter ? ` Try again in about ${err.retryAfter} seconds.` : "";
  return base + hint;
}

// Shown for ?auth_error=<code> after a failed Google sign-in. Unknown codes get the generic text.
const AUTH_ERRORS = {
  access_denied: "Sign-in was cancelled or not allowed. You can try again.",
  state_invalid: "The sign-in attempt expired or could not be verified. Please try again.",
  token_invalid: "Google's answer could not be verified. Please try again.",
  email_unverified: "Your Google email address is not verified, so it cannot be used to sign in.",
};

// The API answered 401 (never signed in, session expired or signed out): show the signed-out state.
function showSignedOut() {
  epoch++;
  setState({
    auth: { status: "signed-out", user: null },
    patients: { status: "signed-out", items: [], error: null },
    patient: { status: "idle", data: null, error: null },
    selectedId: null,
    sending: false,
    messages: {},
    timeline: [],
    audit: EMPTY_AUDIT,
    evidence: { status: "idle", chunks: [], error: null },
    activeChunk: { status: "idle", data: null, error: null },
  });
}

const EMPTY_AUDIT = { status: "idle", sessionId: null, groups: [], total: 0, error: null };

// Friendly text for a failed activity request (401 is handled by the caller).
function auditErrorText(err) {
  if (err instanceof api.ApiError) {
    if (err.status === 404) return "This conversation has no activity record, or it does not belong to you.";
    if (err.status === 429) return `Too many requests. Try again in ${err.retryAfter || "a few"} seconds.`;
    if (err.status === 503) return "The activity log is not available right now (the database is not reachable). Try again in a moment.";
  }
  return errorText(err);
}

// Loads the real audit log of one conversation into the timeline. `quiet` keeps the old list on screen while refreshing.
async function loadAudit(sessionId, { quiet = false } = {}) {
  if (api.isMockSource() || !sessionId) return;
  const mine = epoch;
  const keep = state.audit.sessionId === sessionId ? state.audit : EMPTY_AUDIT;
  if (!quiet || keep.groups.length === 0) setState({ audit: { ...keep, status: "loading", sessionId } });
  try {
    const page = await api.getAuditTimeline(sessionId);
    if (mine !== epoch || state.audit.sessionId !== sessionId) return;
    setState({ audit: { status: "ready", sessionId, groups: page.items, total: page.total, error: null } });
  } catch (err) {
    if (mine !== epoch) return;
    if (err instanceof api.AuthError) return showSignedOut();
    setState({ audit: { ...keep, status: "error", sessionId, error: auditErrorText(err) } });
  }
}

function currentSessionId() {
  return state.selectedId ? state.sessions[state.selectedId]?.id || null : null;
}

async function loadPatients() {
  const mine = ++epoch;
  setState({
    patients: { status: "loading", items: [], error: null },
    patient: { status: "idle", data: null, error: null },
    selectedId: null,
    sending: false,
    audit: EMPTY_AUDIT,
    activeChunk: { status: "idle", data: null, error: null },
  });
  try {
    const items = await api.listPatients();
    if (mine !== epoch) return;
    setState({ patients: { status: items.length ? "ready" : "empty", items, error: null } });
    if (items.length) selectPatient(items[0].id);
  } catch (err) {
    if (mine !== epoch) return;
    if (err instanceof api.AuthError) return showSignedOut();
    setState({ patients: { status: "error", items: [], error: errorText(err) } });
  }
}

async function selectPatient(id) {
  const mine = epoch;
  const known = state.sessions[id]?.id || null;
  setState({ selectedId: id, patient: { status: "loading", data: null, error: null }, audit: known ? { ...EMPTY_AUDIT, sessionId: known } : EMPTY_AUDIT });
  if (known) loadAudit(known);
  try {
    const data = await api.getPatient(id);
    if (mine !== epoch || state.selectedId !== id) return;
    setState({ patient: { status: "ready", data, error: null } });
    resumeConversation(id);
  } catch (err) {
    if (mine !== epoch || state.selectedId !== id) return;
    if (err instanceof api.AuthError) return showSignedOut();
    setState({ patient: { status: "error", data: null, error: errorText(err) } });
  }
}

// Resumes the newest chat session of this patient (best effort: a failure here must not block asking a new question).
async function resumeConversation(patientId) {
  if (api.isMockSource() || state.demo !== "ready" || state.sessions[patientId]?.id || state.messages[patientId]?.length) return;
  const mine = epoch;
  try {
    const session = await api.latestSession(patientId);
    if (!session || mine !== epoch || state.selectedId !== patientId) return;
    const items = await api.listMessages(session.session_id);
    if (mine !== epoch || state.selectedId !== patientId || state.messages[patientId]?.length) return;
    const lastAnswer = [...items].reverse().find((item) => item.answer)?.answer;
    const patch = {
      sessions: { ...state.sessions, [patientId]: { id: session.session_id } },
      messages: { ...state.messages, [patientId]: items.map(messageFromApi) },
    };
    if (lastAnswer && lastAnswer.evidence.length) {
      patch.evidence = { status: "ready", chunks: evidenceFromAnswer(lastAnswer), error: null };
    }
    setState(patch);
    loadAudit(session.session_id);
  } catch (err) {
    if (err instanceof api.AuthError) showSignedOut();
  }
}

// Mock demo path (?source=mock): fixed mock replies, no network.
async function sendMock(patientId, mode, text, mine) {
  const { reply, chunks, events } = await api.askQuestion({ patientId, mode, text });
  if (mine !== epoch) return;
  addMessage(patientId, { role: "assistant", text: reply.text, citations: reply.citations, mode });
  const patch = { sending: false, timeline: [...state.timeline, ...events] };
  if (mode !== "gk") {
    patch.evidence = { status: chunks.length ? "ready" : "no-evidence", chunks, error: null };
    patch.activeChunk = { status: "idle", data: null, error: null };
  }
  setState(patch);
}

// Real path: one chat session per patient conversation, one POST per question with a fresh Idempotency-Key.
async function sendLive(patientId, mode, text, mine) {
  await api.checkDemoState();
  let entry = state.sessions[patientId];
  if (!entry?.id) {
    const session = await api.createSession(patientId);
    entry = { id: session.session_id };
    if (mine !== epoch) return;
    setState({ sessions: { ...state.sessions, [patientId]: entry }, audit: { ...EMPTY_AUDIT, sessionId: entry.id } });
  }
  // While a (slow) answer is prepared the audit log shows the question as running; the steps appear when it finishes.
  const poll = setInterval(() => loadAudit(entry.id, { quiet: true }), 5000);
  let answer;
  try {
    answer = await api.postMessage(entry.id, { content: text, mode: API_MODE[mode], key: api.newIdempotencyKey() });
  } catch (err) {
    loadAudit(entry.id, { quiet: true }); // a failed run is in the audit log too
    throw err;
  } finally {
    clearInterval(poll);
  }
  if (mine !== epoch) return;
  addMessage(patientId, { role: "assistant", text: answer.content, mode, kind: "answer", answer });
  loadAudit(entry.id, { quiet: true });
  const chunks = evidenceFromAnswer(answer);
  const patch = { sending: false };
  if (mode === "gk") {
    patch.evidence = { status: "idle", chunks: [], error: null };
  } else {
    patch.evidence = { status: chunks.length ? "ready" : "no-evidence", chunks, error: null };
  }
  patch.activeChunk = { status: "idle", data: null, error: null };
  setState(patch);
}

async function sendQuestion(text) {
  const patientId = state.selectedId;
  const mode = state.mode;
  if (!patientId || state.sending || !text.trim()) return;
  const mine = epoch;

  addMessage(patientId, { role: "user", text });
  setState({ sending: true, sendingSince: Date.now(), lastQuestion: text });
  const ticker = setInterval(() => updateChatStatus(state), 1000); // the elapsed-seconds counter
  try {
    if (api.isMockSource()) await sendMock(patientId, mode, text, mine);
    else await sendLive(patientId, mode, text, mine);
  } catch (err) {
    if (mine !== epoch) return;
    if (err instanceof api.AuthError) return showSignedOut();
    addMessage(patientId, { role: "assistant", kind: "error", text: friendlyText(err), mode });
    setState({
      sending: false,
      evidence: mode === "gk" ? state.evidence : { status: "error", chunks: [], error: friendlyText(err) },
    });
  } finally {
    clearInterval(ticker);
  }
}

// Starts a fresh conversation for the selected patient (the next question creates a new chat session).
function startNewConversation() {
  const patientId = state.selectedId;
  if (!patientId || state.sending) return;
  setState({
    sessions: { ...state.sessions, [patientId]: { id: null } },
    messages: { ...state.messages, [patientId]: [] },
    evidence: { status: "idle", chunks: [], error: null },
    activeChunk: { status: "idle", data: null, error: null },
    timeline: [],
    audit: EMPTY_AUDIT,
  });
}

// Rates an answer (one rating per answer; the server keeps the first). Returns the API's reply for the feedback row.
function sendFeedback(answer, rating, reason) {
  return api.postFeedback(answer.session_id, answer.message_id, { rating, reason });
}

// Click or keyboard activation of a citation badge: show that answer's evidence and highlight the cited chunk with its quote.
function focusCitation(answer, chunkId) {
  const chunks = evidenceFromAnswer(answer);
  const chunk = chunks.find((c) => c.citation_id === chunkId);
  setState({
    evidence: { status: "ready", chunks, error: null },
    activeChunk: chunk ? { status: "ready", data: chunk, error: null } : { status: "idle", data: null, error: null },
  });
  requestAnimationFrame(() => document.querySelector("#evidence-body .excerpt")?.focus());
}

async function openCitation(id) {
  // Real retrieved chunks are already in the evidence list: open them without any request.
  const retrieved = state.evidence.chunks.find((c) => c.citation_id === id && c.real);
  if (retrieved) return setState({ activeChunk: { status: "ready", data: retrieved, error: null } });
  const mine = epoch;
  setState({ activeChunk: { status: "loading", data: null, error: null } });
  try {
    const data = await api.getChunk(id);
    if (mine !== epoch) return;
    setState({ activeChunk: { status: "ready", data, error: null } });
  } catch (err) {
    if (mine !== epoch) return;
    setState({ activeChunk: { status: "error", data: null, error: errorText(err) } });
  }
}

function setMode(mode) {
  if (MODES[mode]) setState({ mode });
}

function setDemo(value) {
  api.setDemoState(value);
  const url = new URL(window.location.href);
  if (value === "ready") url.searchParams.delete("state");
  else url.searchParams.set("state", value);
  history.replaceState(null, "", url);
  setState({ demo: api.getDemoState(), messages: {}, timeline: [], audit: EMPTY_AUDIT, evidence: { status: "idle", chunks: [], error: null } });
  loadPatients();
}

const actions = {
  selectPatient,
  openCitation,
  reload: () => setDemo(state.demo),
  retryLast: () => state.lastQuestion && sendQuestion(state.lastQuestion),
  focusCitation,
  sendFeedback,
  refreshAudit: () => loadAudit(currentSessionId()),
};

function render(s) {
  renderAuth(s);
  renderPatients(s, actions);
  renderPatientDetail(s, actions);
  renderChat(s, actions);
  renderEvidence(s, actions);
  renderTimeline(s, actions);
  renderMode(s);
  document.getElementById("admin-link").hidden = !(s.auth.status === "signed-in" && s.auth.user?.role === "admin");
  document.getElementById("demo-state").value = s.demo;
}

function wireControls() {
  for (const input of document.querySelectorAll('input[name="source-mode"]')) {
    input.addEventListener("change", () => setMode(input.value));
  }
  const form = document.getElementById("chat-form");
  const field = document.getElementById("chat-input");
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const text = field.value.trim();
    if (!text) return;
    field.value = "";
    sendQuestion(text);
  });
  document.getElementById("demo-state").addEventListener("change", (e) => setDemo(e.target.value));
  document.getElementById("demo-reset").addEventListener("click", () => setDemo("ready"));
  document.getElementById("signin-button").href = api.loginUrl;
  document.getElementById("new-conversation").addEventListener("click", startNewConversation);
  document.getElementById("timeline-refresh").addEventListener("click", () => actions.refreshAudit());
  document.getElementById("signout-button").addEventListener("click", async () => {
    try {
      await api.signOut();
    } catch (err) {
      if (!(err instanceof api.AuthError)) {
        setState({ authMessage: `Could not sign out: ${errorText(err)}` });
        return;
      }
    }
    showSignedOut();
  });

  // Footer legend: add the same icons used by the badges in the panels.
  for (const [kind, badge] of [["fact", ".prov-fact"], ["evidence", ".prov-evidence"], ["interpretation", ".prov-interpretation"]]) {
    document.querySelector(`.legend ${badge}`)?.prepend(icon(PROVENANCE[kind].icon));
  }
}

function showMockLabel() {
  // Always visible when mock patients are shown, so demo data is never mistaken for database data.
  const label = document.createElement("p");
  label.className = "mock-source-label";
  label.setAttribute("role", "status");
  label.textContent = "DEMO DATA (mock): patients are not coming from the database.";
  document.querySelector(".banner").after(label);
}

// Reads ?auth_error=..., returns a friendly message and removes the parameter from the address bar.
function consumeAuthError() {
  const url = new URL(window.location.href);
  const code = url.searchParams.get("auth_error");
  if (code === null) return null;
  url.searchParams.delete("auth_error");
  history.replaceState(null, "", url);
  return Object.hasOwn(AUTH_ERRORS, code) ? AUTH_ERRORS[code] : "Sign-in failed. Please try again.";
}

async function start() {
  if (api.isMockSource()) {
    // Demo mode never talks to the API, so there is nothing to sign in to.
    setState({ auth: { status: "mock", user: null } });
    loadPatients();
    return;
  }
  try {
    const user = await api.getMe();
    setState({ auth: { status: "signed-in", user } });
    loadPatients();
  } catch (err) {
    if (err instanceof api.AuthError) {
      showSignedOut();
    } else {
      setState({
        auth: { status: "signed-out", user: null },
        patients: { status: "error", items: [], error: errorText(err) },
      });
    }
  }
}

subscribe(render);
wireControls();
if (api.isMockSource()) showMockLabel();
const requested = new URLSearchParams(window.location.search).get("state") || "ready";
api.setDemoState(requested);
setState({ demo: api.getDemoState(), authMessage: consumeAuthError() });
start();
