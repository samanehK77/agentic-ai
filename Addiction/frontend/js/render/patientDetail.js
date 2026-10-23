// Patient detail view: only synthetic patient facts live here.
import { el, provenanceBadge } from "./dom.js";
import { stateBlock } from "./states.js";

const section = (title, content) => el("section", { class: "detail-section" }, el("h4", { text: title }), content);
const list = (items) => el("ul", {}, items.map((text) => el("li", { text })));

export function renderPatientDetail(state, actions) {
  const container = document.getElementById("detail-body");
  const { status, data, error } = state.patient;

  if (state.patients.status === "loading") return container.replaceChildren(stateBlock("loading", { title: "Loading…" }));
  if (state.patients.status !== "ready") {
    return container.replaceChildren(stateBlock("empty", { title: "No patient selected", message: "There are no patients to show in this state." }));
  }
  if (status === "idle") {
    return container.replaceChildren(stateBlock("empty", { title: "No patient selected", message: "Choose a patient from the explorer." }));
  }
  if (status === "loading") return container.replaceChildren(stateBlock("loading", { title: `Loading ${state.selectedId}…` }));
  if (status === "error") {
    return container.replaceChildren(stateBlock("error", { title: "Could not load patient", message: error, onRetry: () => actions.selectPatient(state.selectedId) }));
  }

  container.replaceChildren(
    el("article", { class: "prov-box prov-fact-box" },
      el("header", { class: "detail-header" },
        el("h3", { text: `${data.id} · ${data.category}` }),
        provenanceBadge("fact"),
      ),
      el("p", { class: "detail-meta", text: `${data.age} years · ${data.sex} · fictional adult` }),
      section("Synthetic background", el("p", { text: data.background })),
      section("Observed behaviors", list(data.behaviors)),
      section("History", el("ul", {}, data.history.map((h) => el("li", {}, el("strong", { text: `${h.period}: ` }), h.event)))),
      section("Triggers", list(data.triggers)),
      section("Previous interventions", el("ul", {}, data.previous_interventions.map((i) =>
        el("li", {}, el("strong", { text: `${i.name} (${i.period}): ` }), i.outcome)))),
      section("Progress", el("p", {}, el("strong", { text: `${data.progress.status}. ` }), data.progress.note)),
    ),
  );
}
