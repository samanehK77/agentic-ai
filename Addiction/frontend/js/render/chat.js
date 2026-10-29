// Chat panel. The log is append-only so the aria-live region announces only new messages.
import { el, provenanceBadge } from "./dom.js";

let renderedFor = null;
let renderedCount = 0;

export function renderChat(state, actions) {
  const log = document.getElementById("chat-log");
  const input = document.getElementById("chat-input");
  const send = document.getElementById("chat-send");
  const context = document.getElementById("chat-context");
  const status = document.getElementById("chat-status");

  const patient = state.patients.items.find((p) => p.id === state.selectedId);
  const ready = state.patient.status === "ready" && Boolean(patient);

  // Patient context line (a patient fact, so it uses the fact style).
  context.replaceChildren(
    provenanceBadge("fact"),
    el("span", { text: ready ? ` Context: ${patient.id} · ${patient.category}` : " No patient selected" }),
  );
  context.className = `chat-context prov-fact-box${ready ? "" : " is-empty"}`;

  const disabled = !ready || state.sending;
  input.disabled = disabled;
  send.disabled = disabled;
  input.placeholder = ready ? "Ask a question about this synthetic case…" : "Select a patient to start";
  const live = state.auth.status !== "mock" && state.mode !== "gk";
  status.textContent = state.sending ? (live ? "Searching the documents…" : "Waiting for a mock reply…") : "";

  const messages = (state.selectedId && state.messages[state.selectedId]) || [];

  // Switching patient: rebuild the log without announcing old messages.
  if (renderedFor !== state.selectedId || messages.length < renderedCount) {
    log.setAttribute("aria-live", "off");
    log.replaceChildren();
    renderedFor = state.selectedId;
    renderedCount = 0;
    if (messages.length === 0) log.append(emptyHint(ready));
    requestAnimationFrame(() => log.setAttribute("aria-live", "polite"));
  }

  if (messages.length > renderedCount) {
    log.querySelector(".chat-empty")?.remove();
    for (const message of messages.slice(renderedCount)) log.append(renderMessage(message, actions));
    renderedCount = messages.length;
    log.scrollTop = log.scrollHeight;
  }
  if (messages.length === 0) log.replaceChildren(emptyHint(ready));
}

function emptyHint(ready) {
  return el("p", { class: "chat-empty", text: ready
    ? "No messages yet. Type a question below. General Knowledge replies are fixed mock text; RAG and Both show retrieved evidence only (answer generation arrives in Batch 07)."
    : "Select a patient to start a conversation." });
}

function renderMessage(message, actions) {
  if (message.role === "user") {
    return el("div", { class: "message message-user" },
      el("p", { class: "message-who", text: "You" }),
      el("p", { class: "message-text", text: message.text }), // textContent only
    );
  }
  if (message.kind === "error") {
    return el("div", { class: "message message-error", role: "alert" },
      el("p", { class: "message-who", text: "Error" }),
      el("p", { class: "message-text", text: message.text }),
    );
  }
  const citations = message.citations || [];
  if (message.kind === "placeholder") {
    // Not a model answer: no interpretation badge and no citations. The evidence is in the Evidence Inspector.
    return el("div", { class: "message message-placeholder" },
      el("div", { class: "message-head" }, el("span", { class: "chip", text: `Mode: ${message.mode.toUpperCase()}` }),
        el("span", { class: "chip chip-warn", text: "No answer generated" })),
      el("p", { class: "message-text", text: message.text }),
    );
  }
  return el("div", { class: "message message-assistant prov-interpretation-box" },
    el("div", { class: "message-head" }, provenanceBadge("interpretation"),
      el("span", { class: "chip", text: `Mode: ${message.mode.toUpperCase()}` })),
    el("p", { class: "message-text", text: message.text }),
    citations.length > 0 && el("p", { class: "citation-row" },
      el("span", { class: "citation-label", text: "Citations (MOCK): " }),
      citations.map((id) => el("button", { type: "button", class: "citation-chip", dataset: { citation: id },
        "aria-label": `Open excerpt ${id}`, onclick: () => actions.openCitation(id), text: id }))),
  );
}
