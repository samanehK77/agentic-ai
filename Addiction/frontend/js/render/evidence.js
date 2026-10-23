// Evidence inspector: retrieved MOCK chunks plus the opened excerpt.
import { el, provenanceBadge } from "./dom.js";
import { stateBlock } from "./states.js";

export function renderEvidence(state, actions) {
  const container = document.getElementById("evidence-body");
  const focusedId = document.activeElement?.closest?.("#evidence-body")
    ? document.activeElement.dataset.citation : null;

  const parts = [];
  const retrieving = state.mode !== "gk";

  if (state.demo === "loading" || (state.sending && retrieving)) {
    parts.push(stateBlock("loading", { title: "Retrieving mock evidence…" }));
  } else if (!retrieving) {
    parts.push(stateBlock("empty", {
      title: "No retrieval in General Knowledge mode",
      message: "Answers in this mode use no retrieved documents, so there is no evidence to inspect. Switch to RAG or Both to see mock excerpts.",
    }));
  } else if (state.evidence.status === "error") {
    parts.push(stateBlock("error", { title: "Retrieval failed", message: state.evidence.error, onRetry: actions.retryLast }));
  } else if (state.evidence.status === "no-evidence") {
    parts.push(stateBlock("no-evidence", {
      title: "No supporting evidence found",
      message: "Nothing in the mock corpus matched. A real answer must say so and must not invent citations.",
    }));
  } else if (state.evidence.status === "idle" || state.evidence.chunks.length === 0) {
    parts.push(stateBlock("empty", { title: "No evidence yet", message: "Ask a question in RAG or Both mode to see retrieved mock excerpts." }));
  } else {
    parts.push(el("ul", { class: "chunk-list", "aria-label": "Retrieved mock chunks" },
      state.evidence.chunks.map((c) => chunkItem(c, state, actions))));
  }

  // Opened excerpt (selected from a citation or from the list).
  const active = state.activeChunk;
  if (active.status === "loading") parts.push(stateBlock("loading", { title: "Opening excerpt…" }));
  else if (active.status === "error") parts.push(stateBlock("error", { title: "Could not open excerpt", message: active.error }));
  else if (active.status === "ready") parts.push(excerpt(active.data));

  container.replaceChildren(...parts);
  if (focusedId) container.querySelector(`[data-citation="${focusedId}"]`)?.focus();
}

function chunkItem(chunk, state, actions) {
  const open = state.activeChunk.data?.citation_id === chunk.citation_id;
  return el("li", {},
    el("button", { type: "button", class: "chunk-card", dataset: { citation: chunk.citation_id },
        "aria-pressed": open ? "true" : "false", onclick: () => actions.openCitation(chunk.citation_id) },
      el("span", { class: "chunk-top" }, el("span", { class: "citation-id", text: chunk.citation_id }),
        el("span", { class: "chip chip-mock", text: "MOCK" }),
        el("span", { class: "chunk-score", text: `score ${chunk.score.toFixed(2)}` })),
      el("span", { class: "chunk-doc", text: chunk.document }),
      el("span", { class: "chunk-where", text: `${chunk.section} · p. ${chunk.page}` }),
    ),
  );
}

function excerpt(chunk) {
  return el("article", { class: "prov-box prov-evidence-box excerpt", "aria-label": `Excerpt ${chunk.citation_id}` },
    el("header", { class: "detail-header" },
      el("h3", { text: `${chunk.citation_id} · MOCK excerpt` }),
      provenanceBadge("evidence")),
    el("p", { class: "detail-meta", text: `${chunk.document} · ${chunk.section} · p. ${chunk.page}` }),
    el("blockquote", { text: chunk.text }),
    el("p", { class: "note", text: "MOCK: invented placeholder text. It is not from any real document." }),
  );
}
