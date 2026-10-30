// Administrator page: audit summary and event list. Metadata and statistics only. All text uses textContent (through el()).
import * as api from "./api.js";
import { el } from "./render/dom.js";
import { stateBlock } from "./render/states.js";

const PAGE = 25;
const EVENT_TYPES = [
  "sign_in_succeeded", "sign_in_failed", "sign_out", "patient_viewed", "session_created", "question_submitted", "node_executed",
  "retrieval_executed", "llm_request", "citation_validated", "answer_returned", "pipeline_error", "access_denied", "feedback_submitted"];

const $ = (id) => document.getElementById(id);
let offset = 0;
let total = 0;

const percent = (value) => (value == null ? "n/a" : `${(value * 100).toFixed(1)} %`);
const ms = (value) => (value == null ? "n/a" : `${Math.round(value)} ms`);

function message(kind, title, text) {
  $("admin-status").replaceChildren(stateBlock(kind, { title, message: text }));
}

function errorText(err) {
  if (err instanceof api.AuthError) return "You are not signed in. Sign in on the main page first.";
  if (err instanceof api.ApiError) {
    if (err.status === 403) return "This page is for administrators only.";
    if (err.status === 429) return `Too many requests. Try again in ${err.retryAfter || "a few"} seconds.`;
    if (err.status === 503) return "The audit log is not available right now (the database is not reachable).";
    if (err.status === 422) return "A filter value is not valid (check the user id and the dates).";
  }
  return err instanceof Error ? err.message : String(err);
}

// A date input ("2026-11-01") -> the start of that day in UTC; the end date is inclusive, so it becomes the next day's start.
function dayStart(value, addDays = 0) {
  if (!value) return "";
  const date = new Date(`${value}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + addDays);
  return date.toISOString();
}

function card(label, value) {
  return el("div", { class: "admin-card" }, el("div", { class: "value", text: String(value) }), el("div", { class: "label", text: label }));
}

async function loadSummary() {
  const summary = await api.getAdminAuditSummary({ date_from: dayStart($("sum-from").value), date_to: dayStart($("sum-to").value, 1) });
  $("admin-cards").replaceChildren(
    card("Answers returned", summary.answers_returned), card("Pipeline errors", summary.pipeline_errors),
    card("Error rate", percent(summary.error_rate)), card("No-evidence rate", percent(summary.no_evidence_rate)),
    card("Answer latency p50", ms(summary.answer_latency_p50_ms)), card("Answer latency p95", ms(summary.answer_latency_p95_ms)),
    card("Audit write failures (since server start)", summary.audit_write_failures),
  );
  const days = [...new Set(summary.per_day.map((r) => r.day))];
  const types = [...new Set(summary.per_day.map((r) => r.event_type))];
  const count = (day, type) => summary.per_day.find((r) => r.day === day && r.event_type === type)?.count ?? 0;
  $("admin-days").replaceChildren(days.length === 0 ? el("p", { class: "note", text: "No events in this range." }) :
    el("table", { class: "admin-table" },
      el("thead", {}, el("tr", {}, el("th", { text: "Day (UTC)" }), types.map((t) => el("th", { text: t.replaceAll("_", " ") })))),
      el("tbody", {}, days.map((day) => el("tr", {}, el("th", { scope: "row", text: day }), types.map((t) => el("td", { text: String(count(day, t)) })))))));
}

function filters() {
  return {
    event_type: $("f-type").value, outcome: $("f-outcome").value, user_id: $("f-user").value.trim(),
    date_from: dayStart($("f-from").value), date_to: dayStart($("f-to").value, 1),
  };
}

async function loadEvents() {
  const page = await api.getAdminAuditEvents({ ...filters(), limit: PAGE, offset });
  total = page.total;
  $("admin-events").replaceChildren(page.items.length === 0 ? el("p", { class: "note", text: "No events match." }) :
    el("table", { class: "admin-table" },
      el("thead", {}, el("tr", {}, ["Time", "Type", "Outcome", "Latency", "Error code", "Correlation", "User", "Metadata"].map((h) => el("th", { text: h })))),
      el("tbody", {}, page.items.map((e) => el("tr", {},
        el("td", { text: new Date(e.occurred_at).toLocaleString() }), el("td", { text: e.event_type }), el("td", { text: e.outcome }),
        el("td", { text: e.latency_ms == null ? "" : `${e.latency_ms} ms` }), el("td", { text: e.error_code || "" }),
        el("td", { text: e.correlation_id.slice(0, 8), title: e.correlation_id }), el("td", { text: e.user_id ? e.user_id.slice(0, 8) : "(none)", title: e.user_id || "" }),
        el("td", { class: "meta", text: JSON.stringify(e.metadata) }))))));
  const from = total === 0 ? 0 : offset + 1;
  $("page-info").textContent = `${from}–${Math.min(offset + PAGE, total)} of ${total}`;
  $("page-prev").disabled = offset === 0;
  $("page-next").disabled = offset + PAGE >= total;
}

async function refresh() {
  try {
    await Promise.all([loadSummary(), loadEvents()]);
    $("admin-status").replaceChildren();
  } catch (err) {
    message("error", "Could not load the audit data", errorText(err));
  }
}

async function start() {
  for (const type of EVENT_TYPES) $("f-type").append(el("option", { value: type, text: type }));
  message("loading", "Loading…", "");
  try {
    const me = await api.getMe();
    if (me.role !== "admin") return message("error", "Administrators only", "This page is for administrators. Students can see their own activity in the main workspace.");
  } catch (err) {
    return message("error", "Cannot open the admin page", errorText(err));
  }
  $("admin-summary-section").hidden = false;
  $("admin-events-section").hidden = false;
  $("admin-refresh").addEventListener("click", refresh);
  $("sum-apply").addEventListener("click", () => loadSummary().catch((err) => message("error", "Could not load the summary", errorText(err))));
  $("event-filters").addEventListener("submit", (event) => {
    event.preventDefault();
    offset = 0;
    loadEvents().catch((err) => message("error", "Could not load the events", errorText(err)));
  });
  $("page-prev").addEventListener("click", () => { offset = Math.max(0, offset - PAGE); loadEvents().catch((err) => message("error", "Could not load the events", errorText(err))); });
  $("page-next").addEventListener("click", () => { offset += PAGE; loadEvents().catch((err) => message("error", "Could not load the events", errorText(err))); });
  refresh();
}

start();
