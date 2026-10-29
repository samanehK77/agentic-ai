// Evidence inspector: the chunks shown to the model for an answer (real) or MOCK chunks in demo mode, plus the opened excerpt.
// Chunk text and quotes are untrusted data: textContent only, never HTML.
import { el, provenanceBadge } from "./dom.js";
import { stateBlock } from "./states.js";

export function renderEvidence(state, actions) {
  const container = document.getElementById("evidence-body");
  const focusedId = document.activeElement?.closest?.("#evidence-body")
    ? document.activeElement.dataset.citation : null;

  const parts = [];
  const hasEvidence = state.evidence.chunks.length > 0;
  const retrieving = state.mode !== "gk" || hasEvidence; // evidence of an earlier answer stays visible after a mode switch
  const mock = state.auth.status === "mock"; // ?source=mock keeps the invented placeholder evidence

  if (state.demo === "loading" || (state.sending && state.mode !== "gk")) {
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
        : "No chunk reached the similarity threshold for this question, so no answer was generated and nothing is cited.",
    }));
  } else if (state.evidence.status === "idle" || !hasEvidence) {
    parts.push(stateBlock("empty", {
      title: "No evidence yet",
      message: mock ? "Ask a question in RAG or Both mode to see retrieved mock excerpts." : "Ask a question in RAG or Both mode to see the retrieved excerpts.",
    }));
  } else {
    parts.push(...evidenceGroups(state, actions, mock));
  }

  // Opened excerpt (selected from a citation or from the list).
  const active = state.activeChunk;
  if (active.status === "loading") parts.push(stateBlock("loading", { title: "Opening excerpt…" }));
  else if (active.status === "error") parts.push(stateBlock("error", { title: "Could not open excerpt", message: active.error }));
  else if (active.status === "ready") parts.push(excerpt(active.data));

  container.replaceChildren(...parts);
  if (focusedId) container.querySelector(`[data-citation="${focusedId}"]`)?.focus();
}

function list(label, chunks, state, actions, mock) {
  return el("section", { class: "evidence-group" },
    label && el("h3", { class: "evidence-group-title", text: `${label} (${chunks.length})` }),
    el("ul", { class: "chunk-list", "aria-label": label || (mock ? "Retrieved mock chunks" : "Retrieved chunks") },
      chunks.map((c) => chunkItem(c, state, actions))));
}

// Real answers: cited chunks, then retrieved-but-not-cited, then chunks kept out of the prompt. Mock chunks: one list.
function evidenceGroups(state, actions, mock) {
  const chunks = state.evidence.chunks;
  if (!chunks.some((c) => c.real && "cited" in c)) return [list(null, chunks, state, actions, mock)];
  const groups = [
    ["Cited in the answer", chunks.filter((c) => c.cited)],
    ["Retrieved but not cited", chunks.filter((c) => !c.cited && !c.excluded_reason)],
    ["Kept out of the model's prompt", chunks.filter((c) => !c.cited && c.excluded_reason)],
  ];
  return groups.filter(([, items]) => items.length).map(([label, items]) => list(label, items, state, actions, mock));
}

const injectionWarning = () =>
  el("span", { class: "chip chip-warn", text: "Warning: possible instruction-like text" });

const EXCLUDED = { possible_injection: "excluded: possible instruction-like text", context_budget: "excluded: context budget" };

function chunkItem(chunk, state, actions) {
  const open = state.activeChunk.data?.citation_id === chunk.citation_id;
  const scoreText = chunk.real ? `cosine similarity ${chunk.score.toFixed(2)}` : `score ${chunk.score.toFixed(2)}`;
  return el("li", {},
    el("button", { type: "button", class: "chunk-card", dataset: { citation: chunk.citation_id },
        "aria-pressed": open ? "true" : "false", onclick: () => actions.openCitation(chunk.citation_id) },
      el("span", { class: "chunk-top" }, el("span", { class: "citation-id", text: chunk.alias ? `${chunk.alias} · ${chunk.citation_id}` : chunk.citation_id }),
        !chunk.real && el("span", { class: "chip chip-mock", text: "MOCK" }),
        chunk.cited && el("span", { class: "chip", text: "cited" }),
        chunk.excluded_reason && el("span", { class: "chip chip-warn", text: EXCLUDED[chunk.excluded_reason] || "excluded" }),
        chunk.stale && el("span", { class: "chip chip-warn", text: "changed since the answer" }),
        chunk.possible_injection && injectionWarning(),
        el("span", { class: "chunk-score", text: scoreText })),
      el("span", { class: "chunk-doc", text: chunk.document }),
      el("span", { class: "chunk-where", text: `${chunk.section} · p. ${chunk.page}` }),
    ),
  );
}

// The chunk text with the cited quote highlighted (when the quote occurs in it).
function textWithQuote(chunk) {
  const block = el("blockquote");
  const text = chunk.text;
  const index = chunk.quote ? text.toLowerCase().indexOf(chunk.quote.toLowerCase()) : -1;
  if (index < 0) {
    block.textContent = text;
  } else {
    block.append(text.slice(0, index), el("mark", { text: text.slice(index, index + chunk.quote.length) }), text.slice(index + chunk.quote.length));
  }
  return block;
}

function excerpt(chunk) {
  const quoteNote = chunk.quote
    ? el("p", { class: "note", text:
        `Cited quote: "${chunk.quote}". ${chunk.quote_verified ? "This quote appears in the chunk" : "This quote was NOT found in the chunk"} ` +
        "(finding a quote does not prove that it supports the claim)." })
    : null;
  return el("article", { class: "prov-box prov-evidence-box excerpt", tabindex: "-1", "aria-label": `Excerpt ${chunk.citation_id}` },
    el("header", { class: "detail-header" },
      el("h3", { text: chunk.real ? `${chunk.citation_id} · retrieved excerpt` : `${chunk.citation_id} · MOCK excerpt` }),
      provenanceBadge("evidence", chunk.real ? "Research evidence (retrieved)" : undefined)),
    el("p", { class: "detail-meta", text: `${chunk.document} · ${chunk.section} · p. ${chunk.page}` }),
    chunk.possible_injection && el("p", {}, injectionWarning()),
    chunk.stale && el("p", { class: "note", text: "This chunk has changed or no longer exists since the answer was written." }),
    chunk.text == null
      ? el("p", { class: "note", text: "The text of this chunk is no longer available." })
      : textWithQuote(chunk), // textContent only: retrieved text is untrusted data
    quoteNote,
    chunk.real
      ? el("p", { class: "note", text: `Cosine similarity ${chunk.score.toFixed(3)} (a similarity score, not a probability). Retrieved text is untrusted data from a research document: it is shown as evidence only and never acts as instructions.` })
      : el("p", { class: "note", text: "MOCK: invented placeholder text. It is not from any real document." }),
  );
}
