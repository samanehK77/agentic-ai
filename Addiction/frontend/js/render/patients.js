// Patient explorer: a list of 10 synthetic patients. Arrow keys move between them.
import { el } from "./dom.js";
import { stateBlock } from "./states.js";

let builtFor = null; // the items array the buttons were built from

export function renderPatients(state, actions) {
  const container = document.getElementById("patients-body");
  const { status, items, error } = state.patients;

  if (status !== "ready") {
    builtFor = null;
    const block =
      status === "loading" ? stateBlock("loading", { title: "Loading patients…" })
      : status === "signed-out" ? stateBlock("empty", { title: "Sign in to see the patients", message: "Use the Sign in with Google button at the top of the page." })
      : status === "error" ? stateBlock("error", { title: "Could not load patients", message: error, onRetry: actions.reload })
      : stateBlock("empty", { title: "No patients to show", message: "The mock patient list is empty in this demo state." });
    container.replaceChildren(block);
    return;
  }

  // Build the buttons once per data load so keyboard focus is not lost on selection.
  if (builtFor !== items) {
    builtFor = items;
    const list = el("ul", { class: "patient-list", "aria-label": "Synthetic patients" });
    for (const p of items) {
      const button = el("button", { type: "button", class: "patient-card", dataset: { id: p.id },
          onclick: () => actions.selectPatient(p.id) },
        el("span", { class: "patient-top" },
          el("span", { class: "patient-id", text: p.id }),
          el("span", { class: "chip", text: p.category }),
        ),
        el("span", { class: "patient-meta", text: `${p.age} y · ${p.sex} · synthetic` }),
        el("span", { class: "patient-line" }, el("strong", { text: "History: " }), p.summary),
        el("span", { class: "patient-line" }, el("strong", { text: "Treatment: " }), p.treatment_summary),
      );
      list.append(el("li", {}, button));
    }
    list.addEventListener("keydown", onKeydown);
    container.replaceChildren(list);
  }

  const buttons = [...container.querySelectorAll(".patient-card")];
  const fallback = state.selectedId ? null : buttons[0];
  for (const button of buttons) {
    const selected = button.dataset.id === state.selectedId;
    if (selected) button.setAttribute("aria-current", "true");
    else button.removeAttribute("aria-current");
    button.tabIndex = selected || button === fallback ? 0 : -1;
  }
}

function onKeydown(event) {
  const keys = { ArrowDown: 1, ArrowUp: -1, Home: "first", End: "last" };
  if (!(event.key in keys)) return;
  const buttons = [...event.currentTarget.querySelectorAll(".patient-card")];
  const index = buttons.indexOf(document.activeElement);
  if (index === -1) return;
  event.preventDefault();
  let next = index;
  if (keys[event.key] === "first") next = 0;
  else if (keys[event.key] === "last") next = buttons.length - 1;
  else next = Math.min(buttons.length - 1, Math.max(0, index + keys[event.key]));
  buttons.forEach((b, i) => (b.tabIndex = i === next ? 0 : -1));
  buttons[next].focus();
}
