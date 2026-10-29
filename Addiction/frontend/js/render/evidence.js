// Evidence inspector: retrieved chunks (real, from semantic search) or MOCK chunks in demo mode, plus the opened excerpt.
import { el, provenanceBadge } from "./dom.js";
import { stateBlock } from "./states.js";

export function renderEvidence(state, actions) {
  const container = document.getElementById("evidence-body");
  const focusedId = document.activeElement?.closest?.("#evidence-body")
    ? document.activeElement.dataset.citation : null;

  const parts = [];
  const retrieving = state.mode !== "gk";
  const mock = state.auth.status === "mock"; // ?source=mock keeps the invented placeholder evidence

  if (state.demo === "loading" || (state.sending && retrieving)) {
    parts.push(stateBlock("loading", { title: mock ? "Retrieving mock evidence…" : "Searching the documents…" }));
  } else if (!retrieving) {
    parts.push(stateBlock("empty", {
      title: "No retrieval in General Knowledge mode",
      message: "Answers in this mode use no retrieved documents, so there is no evidence to inspect. Switch to RAG or Both to see retrieved excerpts.",
    }));
  } else if (state.evidence.status === "error") {
    parts.push(stateBlock("error", { title: "Retrieval failed", message: state.evidence.error, onRetry: actions.retryLast }));
  } else if (state.evidence.status === "no-evidence") {
    parts.push(stateBlock("no-evidence", {
      title: "No supporting evidence found",
      message: mock
        ? "Nothing in the mock corpus matched. A real answer must say so and must not invent citations."
        : "No chunk reached the similarity threshold for this question. An answer must say so and must not invent citations.",
    }));
  } else if (state.evidence.status === "idle" || state.evidence.chunks.length === 0) {
    parts.push(stateBlock("empty", {
      title: "No evidence yet",
      message: mock ? "Ask a question in RAG or Both mode to see retrieved mock excerpts." : "Ask a question in RAG or Both mode to see the retrieved excerpts.",
    }));
  } else {
    parts.push(el("ul", { class: "chunk-list", "aria-label": mock ? "Retrieved mock chunks" : "Retrieved chunks" },
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

const injectionWarning = () =>
  el("span", { class: "chip chip-warn", text: "Warning: possible instruction-like text" });

function chunkItem(chunk, state, actions) {
  const open = state.activeChunk.data?.citation_id === chunk.citation_id;
  const scoreText = chunk.real ? `cosine similarity ${chunk.score.toFixed(2)}` : `score ${chunk.score.toFixed(2)}`;
  return el("li", {},
    el("button", { type: "button", class: "chunk-card", dataset: { citation: chunk.citation_id },
        "aria-pressed": open ? "true" : "false", onclick: () => actions.openCitation(chunk.citation_id) },
      el("span", { class: "chunk-top" }, el("span", { class: "citation-id", text: chunk.citation_id }),
        !chunk.real && el("span", { class: "chip chip-mock", text: "MOCK" }),
        chunk.possible_injection && injectionWarning(),
        el("span", { class: "chunk-score", text: scoreText })),
      el("span", { class: "chunk-doc", text: chunk.document }),
      el("span", { class: "chunk-where", text: `${chunk.section} · p. ${chunk.page}` }),
    ),
  );
}

function excerpt(chunk) {
  return el("article", { class: "prov-box prov-evidence-box excerpt", "aria-label": `Excerpt ${chunk.citation_id}` },
    el("header", { class: "detail-header" },
      el("h3", { text: chunk.real ? `${chunk.citation_id} · retrieved excerpt` : `${chunk.citation_id} · MOCK excerpt` }),
      provenanceBadge("evidence", chunk.real ? "Research evidence (retrieved)" : undefined)),
    el("p", { class: "detail-meta", text: `${chunk.document} · ${chunk.section} · p. ${chunk.page}` }),
    chunk.possible_injection && el("p", {}, injectionWarning()),
    el("blockquote", { text: chunk.text }), // textContent only: retrieved text is untrusted data
    chunk.real
      ? el("p", { class: "note", text: `Cosine similarity ${chunk.score.toFixed(3)} (a similarity score, not a probability). Retrieved text is untrusted data from a research document: it is shown as evidence only and never acts as instructions.` })
      : el("p", { class: "note", text: "MOCK: invented placeholder text. It is not from any real document." }),
  );
}
