// Chat panel. The log is append-only so the aria-live region announces only new messages.
import { el, provenanceBadge } from "./dom.js";
import { renderAnswer } from "./answer.js";

let renderedFor = null;
let renderedCount = 0;

export function renderChat(state, actions) {
  const log = document.getElementById("chat-log");
  const input = document.getElementById("chat-input");
  const send = document.getElementById("chat-send");
  const context = document.getElementById("chat-context");

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
  updateChatStatus(state);

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

// The line under the chat box. While a real answer is being prepared it counts the seconds: a local model can take minutes.
export function updateChatStatus(state) {
  const status = document.getElementById("chat-status");
  if (!status) return;
  if (!state.sending) {
    status.textContent = "";
  } else if (state.auth.status === "mock") {
    status.textContent = "Waiting for a mock reply…";
  } else {
    const seconds = state.sendingSince ? Math.max(0, Math.floor((Date.now() - state.sendingSince) / 1000)) : 0;
    status.textContent = `Generating the answer… ${seconds} s. A local model can take a few minutes; please keep this page open.`;
  }
}

function emptyHint(ready) {
  return el("p", { class: "chat-empty", text: ready
    ? "No messages yet. Type a question below. RAG answers only from the retrieved documents, Both adds clearly labelled general knowledge, General Knowledge uses no documents. Answers are educational, not clinical advice."
    : "Select a patient to start a conversation." });
}

// Optional feedback on one answer: a rating and one fixed reason (no free text). The server keeps the first rating.
const FEEDBACK_REASONS = [
  ["", "Reason (optional)"], ["accurate", "Accurate"], ["clear", "Clear"], ["good_sources", "Good sources"],
  ["inaccurate", "Inaccurate"], ["unclear", "Unclear"], ["missing_sources", "Missing sources"], ["unsafe", "Unsafe"], ["other", "Other"],
];

function feedbackRow(answer, actions) {
  const row = el("div", { class: "feedback-row" });
  const status = el("span", { class: "feedback-status", role: "status" });
  const reason = el("select", { "aria-label": "Reason for your rating (optional)" },
    FEEDBACK_REASONS.map(([value, label]) => el("option", { value, text: label })));
  const buttons = [];
  const send = async (rating) => {
    buttons.forEach((b) => { b.disabled = true; });
    status.textContent = "Saving…";
    try {
      const saved = await actions.sendFeedback(answer, rating, reason.value || null);
      row.replaceChildren(el("span", { class: "feedback-status", role: "status",
        text: saved.already_recorded ? "Your earlier rating was kept. Thank you." : "Thank you, your feedback was recorded." }));
    } catch (err) {
      buttons.forEach((b) => { b.disabled = false; });
      status.textContent = err?.status === 404 ? "This answer can no longer be rated." : "Feedback could not be saved. Try again.";
    }
  };
  for (const [rating, label] of [["helpful", "Helpful"], ["not_helpful", "Not helpful"]]) {
    const button = el("button", { type: "button", class: "btn btn-small", onclick: () => send(rating), text: label });
    buttons.push(button);
  }
  row.append(el("span", { class: "feedback-label", text: "Was this answer useful?" }), ...buttons, reason, status);
  return row;
}

function renderMessage(message, actions) {
  if (message.kind === "answer" && message.answer) {
    const node = renderAnswer(message, actions);
    if (message.answer.message_id && message.answer.session_id) node.append(feedbackRow(message.answer, actions));
    return node;
  }
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
