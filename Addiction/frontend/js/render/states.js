// Shared loading / empty / error / no-evidence blocks.
import { el, icon } from "./dom.js";

const DEFAULTS = {
  loading: { title: "Loading…", message: "Please wait." },
  empty: { title: "Nothing here yet", message: "" },
  error: { title: "Something went wrong", message: "" },
  "no-evidence": { title: "No evidence found", message: "" },
};

export function stateBlock(kind, { title, message, onRetry } = {}) {
  const base = DEFAULTS[kind];
  const block = el(
    "div",
    {
      class: `state state-${kind}`,
      role: kind === "error" ? "alert" : "status",
      "aria-busy": kind === "loading" ? "true" : false,
    },
    icon(kind),
    el("div", { class: "state-text" },
      el("p", { class: "state-title", text: title || base.title }),
      (message || base.message) && el("p", { class: "state-message", text: message || base.message }),
      onRetry && el("button", { type: "button", class: "btn btn-small", onclick: onRetry, text: "Try again" }),
    ),
  );
  return block;
}
