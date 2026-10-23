// All data access goes through this file. Every function is async.
//
// Patient list and detail come from the API (Batch 03). There is NO silent fallback:
// if the API fails, the error reaches the UI's error state. Mock patients are used only
// when the page is opened with ?source=mock (the UI then shows a "DEMO DATA (mock)" label).
// Chat answers and citation chunks stay mock until Batches 05-07.
//
// Demo states (?state=...): ready | loading | empty | error | no-evidence

import { PATIENTS, CHUNKS, REPLIES, TIMELINE_STEPS } from "../data/mock-data.js";
import { API_BASE_URL } from "./config.js";
import { patientDetail, patientListItem } from "./adapters.js";

export const DEMO_STATES = ["ready", "loading", "empty", "error", "no-evidence"];

let demoState = "ready";

export function setDemoState(value) {
  demoState = DEMO_STATES.includes(value) ? value : "ready";
}

export function getDemoState() {
  return demoState;
}

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// Applies the demo state to every request.
async function gate(ms = 200) {
  if (demoState === "loading") {
    return new Promise(() => {}); // never resolves, so the UI stays in its loading state
  }
  await delay(ms);
  if (demoState === "error") {
    throw new Error("Mock error: the demo is simulating a failed request.");
  }
}

const clone = (value) => JSON.parse(JSON.stringify(value));

export function isMockSource() {
  return new URLSearchParams(window.location.search).get("source") === "mock";
}

async function request(path) {
  let response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, { headers: { Accept: "application/json" } });
  } catch {
    throw new Error(`Could not reach the API at ${API_BASE_URL}. Is it running?`);
  }
  if (!response.ok) {
    let message = `The API answered with status ${response.status}.`;
    try {
      const body = await response.json();
      if (body?.error?.message) message = `${body.error.message} (request ${body.error.request_id})`;
    } catch {
      // keep the generic message
    }
    throw new Error(message);
  }
  return response.json();
}

export async function listPatients() {
  await gate();
  if (demoState === "empty") return [];
  if (isMockSource()) {
    return PATIENTS.map(({ id, age, sex, category, summary, treatment_summary }) => ({
      id, age, sex, category, summary, treatment_summary,
    }));
  }
  const page = await request("/api/patients?limit=100");
  return page.items.map(patientListItem);
}

export async function getPatient(id) {
  await gate();
  if (isMockSource()) {
    const patient = PATIENTS.find((p) => p.id === id);
    if (!patient) throw new Error(`Patient ${id} not found.`);
    return clone(patient);
  }
  const encoded = encodeURIComponent(id);
  const [profile, history] = await Promise.all([
    request(`/api/patients/${encoded}`),
    request(`/api/patients/${encoded}/history?limit=100`),
  ]);
  return patientDetail(profile, history.items);
}

export async function getChunk(citationId) {
  await gate(120);
  const chunk = CHUNKS.find((c) => c.citation_id === citationId);
  if (!chunk) throw new Error(`Citation ${citationId} not found.`);
  return clone(chunk);
}

// Returns { reply, chunks, events }. The reply depends only on the mode.
export async function askQuestion({ patientId, mode, text }) {
  await gate(450);
  const usesRetrieval = mode === "rag" || mode === "both";
  const noEvidence = usesRetrieval && demoState === "no-evidence";

  const base = noEvidence ? REPLIES.noEvidence : REPLIES[mode];
  const chunks = base.citations.map((id) => CHUNKS.find((c) => c.citation_id === id));

  const steps = usesRetrieval ? TIMELINE_STEPS.rag : TIMELINE_STEPS.gk;
  const now = Date.now();
  const events = steps.map((step, i) => ({
    id: `evt-${now}-${i}`,
    type: step.type,
    label: step.label + " (mock)",
    detail: step.label === "Chunks retrieved" ? `${chunks.length} chunk(s)` : "",
    time: new Date(now + i * 120).toISOString(),
    patient_id: patientId,
  }));

  return {
    reply: { text: base.text, mode, citations: [...base.citations] },
    chunks: clone(chunks),
    events,
    question: text,
  };
}
