// Activity timeline.
//  - Live (signed in): the real audit log of this conversation, grouped by question (Batch 09). Metadata only.
//  - Demo (?source=mock): the fixed mock events kept in state.timeline.
// All text is set with textContent (through el()); values are codes, counts and ids, never question or chunk text.
import { el, icon, formatTime } from "./dom.js";
import { stateBlock } from "./states.js";
import { auditGroupView } from "../adapters.js";

export function renderTimeline(state, actions) {
  const container = document.getElementById("timeline-body");
  const refresh = document.getElementById("timeline-refresh");
  const live = state.auth.status === "signed-in";
  if (refresh) {
    refresh.hidden = !live;
    refresh.disabled = state.audit.status === "loading";
  }

  if (state.demo === "loading") return container.replaceChildren(stateBlock("loading", { title: "Loading activity…" }));
  if (!live) return renderMock(state, container);

  const audit = state.audit;
  if (state.demo === "empty" || !audit.sessionId) {
    return container.replaceChildren(stateBlock("empty", {
      title: "No activity yet",
      message: "Ask a question to see what happened: steps, retrieval, model request and citation checks.",
    }));
  }
  if (audit.status === "loading" && audit.groups.length === 0) return container.replaceChildren(stateBlock("loading", { title: "Loading activity…" }));
  if (audit.status === "error") {
    return container.replaceChildren(stateBlock("error", { title: "Activity could not be loaded", message: audit.error, onRetry: actions.refreshAudit }));
  }
  const questions = audit.groups.filter((g) => g.kind === "question");
  if (audit.groups.length === 0) {
    return container.replaceChildren(stateBlock("empty", { title: "No activity yet", message: "Ask a question to see what happened." }));
  }

  const views = audit.groups.map(auditGroupView);
  const latestQuestion = views.find((v) => v.kind === "question");
  container.replaceChildren(...[
    latestQuestion?.config && configBox(latestQuestion.config),
    questions.length === 0 && el("p", { class: "note", text: "No question has been asked in this conversation yet." }),
    el("ol", { class: "audit-groups", "aria-label": "Questions and actions, newest first" },
      views.map((view, index) => groupItem(view, index === 0))),
    audit.total > audit.groups.length && el("p", { class: "note", text: `Showing the newest ${audit.groups.length} of ${audit.total}.` }),
  ].filter(Boolean));
}

function configBox(config) {
  const rows = [
    ["Model", config.model], ["Prompt version", config.prompt_version], ["Retrieval threshold", config.retrieval_threshold ?? "none"],
    ["top_k", config.top_k], ["Embedding model", config.embedding_model], ["Embedding fingerprint", config.embedding_fingerprint],
    ["Chunking version", config.chunking_version], ["Configuration fingerprint", config.config_fingerprint],
  ].filter(([, value]) => value !== null && value !== undefined);
  return el("details", { class: "config-box" },
    el("summary", {}, el("span", { text: "Model configuration " }), el("code", { text: config.model || "unknown" })),
    el("dl", { class: "config-list" }, rows.map(([name, value]) => [el("dt", { text: name }), el("dd", { text: String(value) })])),
    el("p", { class: "note", text: "Taken from the latest question. The fingerprint changes when the model, prompt version, retrieval settings, embedding model or chunking change." }),
  );
}

function groupItem(view, open) {
  const attrs = { class: `audit-group audit-${view.outcome}` };
  if (open) attrs.open = true;
  return el("li", {},
    el("details", attrs,
      el("summary", {},
        el("span", { class: `audit-outcome audit-outcome-${view.outcome}`, text: view.outcomeText }),
        el("span", { class: "audit-title", text: ` ${view.title}` }),
        view.totalMs != null && el("span", { class: "audit-total", text: ` · ${formatMs(view.totalMs)} total` }),
        el("span", { class: "timeline-meta" }, el("time", { datetime: view.startedAt, text: formatTime(view.startedAt) }),
          ` · id ${view.shortId}`),
      ),
      view.errorCode && el("p", { class: "audit-diagnosis", role: "note" },
        el("strong", { text: `${view.errorCode}: ` }), view.diagnosis),
      view.outcome === "running" && el("p", { class: "audit-running", role: "status" },
        "Running. The workflow steps appear here when the answer is finished (a local model can take minutes); use Refresh to check."),
      el("ol", { class: "timeline audit-events" }, view.events.map(eventItem)),
    ));
}

function eventItem(evt) {
  const status = evt.status === "skipped" ? "skipped" : evt.status === "error" ? "error" : evt.status === "ended" ? "ended" : evt.status === "denied" ? "error" : "ok";
  return el("li", { class: `timeline-item timeline-${iconFor(evt.type)} timeline-status-${status}` },
    el("span", { class: "timeline-icon" }, icon(iconFor(evt.type))),
    el("span", { class: "timeline-body" },
      el("span", { class: "timeline-label", text: evt.label }),
      status !== "ok" && el("span", { class: "timeline-chip", text: status }),
      evt.badge && el("span", { class: `timeline-chip ${evt.badge.ok ? "chip-ok" : "chip-warn"}`, text: evt.badge.text }),
      evt.detail && el("span", { class: "timeline-detail", text: ` · ${evt.detail}` }),
      evt.latency != null && el("span", { class: "timeline-latency", text: ` · ${formatMs(evt.latency)}` }),
      evt.chunks.length > 0 && el("span", { class: "timeline-chunks", text: `chunks: ${evt.chunks.join(", ")}` }),
    ));
}

const iconFor = (type) => (type === "retrieval_executed" ? "retrieval" : type === "llm_request" ? "generation" : type === "pipeline_error" ? "error" : "info");
const formatMs = (ms) => (ms >= 10000 ? `${(ms / 1000).toFixed(1)} s` : `${ms} ms`);

// ---------------------------------------------------------------- demo mode (?source=mock)

function renderMock(state, container) {
  if (state.timeline.length === 0) {
    return container.replaceChildren(stateBlock("empty", {
      title: "No activity yet",
      message: "Ask a question to see retrieval and generation events.",
    }));
  }
  container.replaceChildren(
    el("ol", { class: "timeline", "aria-label": "Activity events" },
      state.timeline.map((evt) =>
        el("li", { class: `timeline-item timeline-${evt.type} timeline-status-${evt.status || "ok"}` },
          el("span", { class: "timeline-icon" }, icon(evt.type)),
          el("span", { class: "timeline-body" },
            el("span", { class: "timeline-label", text: evt.label }),
            evt.status && evt.status !== "ok" && el("span", { class: "timeline-chip", text: evt.status }),
            evt.detail && el("span", { class: "timeline-detail", text: ` · ${evt.detail}` }),
            el("span", { class: "timeline-meta" }, `${evt.patient_id} · `, el("time", { datetime: evt.time, text: formatTime(evt.time) })),
          ),
        ))),
  );
}
