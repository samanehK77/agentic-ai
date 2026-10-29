// Renders a structured answer (Batch 07). All text comes from the API and is shown with textContent only: model output,
// quotes and chunk text are untrusted data. Content types keep the existing three-way visual separation (patient fact,
// research evidence, model interpretation) plus a clearly different style for general knowledge.
import { el, provenanceBadge } from "./dom.js";

const FLAG_TEXT = {
  unverified_quote: "A quoted passage was not found in the cited chunk.",
  unknown_alias_dropped: "A citation to a source that was not provided was removed.",
  unsupported_research_claim: "A research claim without a valid citation was removed from the answer.",
  general_knowledge_rejected: "A general-knowledge statement was removed (not allowed in RAG mode).",
  research_finding_relabelled_general_knowledge: "A research-type statement was relabelled as general knowledge.",
  citations_dropped: "Citations on a section that may not cite documents were removed.",
  dosing_instruction: "A dosing instruction was withheld.",
  treatment_directive: "An individual treatment directive was withheld.",
  section_withheld: "Part of the answer was withheld by the safety check.",
  truncated_to_fit: "The answer was shortened to fit the size limit.",
  no_evidence: "No chunk reached the similarity threshold, so no answer was generated.",
  personal_crisis_no_answer: "No answer was generated.",
};

function sectionLabel(section) {
  switch (section.kind) {
    case "patient_fact": return provenanceBadge("fact");
    case "research_finding": return provenanceBadge("evidence", "Research finding (retrieved)");
    case "interpretation": return provenanceBadge("interpretation", "Model interpretation");
    case "general_knowledge": return el("span", { class: "badge prov-general" }, "General knowledge (not from the documents)");
    default: return el("span", { class: "badge prov-withheld" }, "Withheld by the safety check");
  }
}

function citationBadge(answer, section, cite, actions) {
  const known = answer.citations.find((c) => c.chunk_id === cite.chunk_id);
  const where = known?.source_title
    ? `${known.source_title}, pages ${known.page_start === known.page_end ? known.page_start : `${known.page_start}-${known.page_end}`}`
    : cite.chunk_id;
  const stale = known?.stale ? " (the chunk has changed or is gone)" : "";
  const label = cite.verified ? cite.alias : `${cite.alias} · unverified`;
  return el("button", {
    type: "button",
    class: `citation-chip${cite.verified ? "" : " unverified"}`,
    dataset: { citation: cite.chunk_id },
    "aria-label": `Citation ${cite.alias}: ${where}. Quote ${cite.verified ? "verified" : "not verified"}${stale}. Show in the evidence inspector`,
    title: `${where}${stale}`,
    onclick: () => actions.focusCitation(answer, cite.chunk_id),
    text: label,
  });
}

export function renderAnswer(message, actions) {
  const answer = message.answer;
  const flags = answer.safety.flags.filter((f) => FLAG_TEXT[f]);
  const children = [
    el("div", { class: "message-head" }, el("span", { class: "chip", text: `Mode: ${message.mode.toUpperCase()}` }),
      answer.no_evidence && el("span", { class: "chip chip-warn", text: "No evidence found" })),
  ];

  if (answer.safety.escalation && answer.safety.notice) {
    children.push(el("div", { class: "notice-escalation", role: "alert" },
      el("strong", { text: "Safety notice. " }), answer.safety.notice));
  }

  if (answer.sections.length === 0 && !(answer.safety.escalation && answer.content === answer.safety.notice)) {
    children.push(el("p", { class: "message-text", text: answer.content }));
  }

  for (const section of answer.sections) {
    children.push(el("div", { class: `answer-section kind-${section.kind}` },
      sectionLabel(section),
      el("p", { class: "message-text", text: section.text }),
      section.citations.length > 0 && el("p", { class: "citation-row" },
        el("span", { class: "citation-label", text: "Citations: " }),
        section.citations.map((cite) => citationBadge(answer, section, cite, actions))),
    ));
  }

  if (answer.unsupported_claims.length > 0) {
    children.push(el("div", { class: "answer-block block-unsupported" },
      el("p", { class: "answer-block-title", text: "Unsupported claims (no valid citation, not part of the answer)" }),
      el("ul", {}, answer.unsupported_claims.map((u) => el("li", { text: u.text })))));
  }
  if (answer.conflicting_evidence.length > 0) {
    children.push(el("div", { class: "answer-block block-conflict" },
      el("p", { class: "answer-block-title", text: "Conflicting evidence" }),
      el("ul", {}, answer.conflicting_evidence.map((c) => el("li", { text: c })))));
  }
  if (answer.limitations) {
    children.push(el("p", { class: "answer-limitations" }, el("strong", { text: "Limitations: " }), answer.limitations));
  }
  const uncited = answer.evidence.filter((e) => !e.cited && !e.excluded_reason).length;
  if (answer.evidence.length > 0) {
    children.push(el("p", { class: "note", text:
      `${answer.evidence.length} chunk(s) retrieved, ${answer.citations.length ? new Set(answer.citations.map((c) => c.chunk_id)).size : 0} cited` +
      `${uncited ? `, ${uncited} not cited` : ""}. Open the Evidence Inspector to read them.` }));
  }
  if (flags.length > 0) {
    children.push(el("details", { class: "answer-notes" },
      el("summary", { text: "Validation notes" }),
      el("ul", {}, flags.map((f) => el("li", { text: FLAG_TEXT[f] })))));
  }
  if (answer.generation.llm_called) {
    const g = answer.generation;
    children.push(el("p", { class: "note", text:
      `Generated by ${g.model} · prompt ${g.prompt_version} · ${g.prompt_tokens}+${g.completion_tokens} tokens · ${g.latency_ms} ms` +
      `${g.repair_attempted ? " · repaired once" : ""}. Not clinical advice.` }));
  }
  return el("div", { class: "message message-answer" }, ...children);
}
