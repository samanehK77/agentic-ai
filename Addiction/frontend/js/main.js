// Entry point: loads data through api.js, updates the store, re-renders panels.
import * as api from "./api.js";
import { state, setState, subscribe, addMessage } from "./state.js";
import { MODES } from "../data/mock-data.js";
import { renderPatients } from "./render/patients.js";
import { renderPatientDetail } from "./render/patientDetail.js";
import { renderChat } from "./render/chat.js";
import { renderEvidence } from "./render/evidence.js";
import { renderTimeline } from "./render/timeline.js";
import { renderMode } from "./render/modeIndicator.js";
import { icon, PROVENANCE } from "./render/dom.js";

// Bumped whenever the demo state changes, so responses from old requests are ignored.
let epoch = 0;

const errorText = (err) => (err instanceof Error ? err.message : String(err));

async function loadPatients() {
  const mine = ++epoch;
  setState({
    patients: { status: "loading", items: [], error: null },
    patient: { status: "idle", data: null, error: null },
    selectedId: null,
    sending: false,
    activeChunk: { status: "idle", data: null, error: null },
  });
  try {
    const items = await api.listPatients();
    if (mine !== epoch) return;
    setState({ patients: { status: items.length ? "ready" : "empty", items, error: null } });
    if (items.length) selectPatient(items[0].id);
  } catch (err) {
    if (mine !== epoch) return;
    setState({ patients: { status: "error", items: [], error: errorText(err) } });
  }
}

async function selectPatient(id) {
  const mine = epoch;
  setState({ selectedId: id, patient: { status: "loading", data: null, error: null } });
  try {
    const data = await api.getPatient(id);
    if (mine !== epoch || state.selectedId !== id) return;
    setState({ patient: { status: "ready", data, error: null } });
  } catch (err) {
    if (mine !== epoch || state.selectedId !== id) return;
    setState({ patient: { status: "error", data: null, error: errorText(err) } });
  }
}

async function sendQuestion(text) {
  const patientId = state.selectedId;
  const mode = state.mode;
  if (!patientId || state.sending || !text.trim()) return;
  const mine = epoch;

  addMessage(patientId, { role: "user", text });
  setState({ sending: true, lastQuestion: text });
  try {
    const { reply, chunks, events } = await api.askQuestion({ patientId, mode, text });
    if (mine !== epoch) return;
    addMessage(patientId, { role: "assistant", text: reply.text, citations: reply.citations, mode });
    const patch = { sending: false, timeline: [...state.timeline, ...events] };
    if (mode !== "gk") {
      patch.evidence = { status: chunks.length ? "ready" : "no-evidence", chunks, error: null };
      patch.activeChunk = { status: "idle", data: null, error: null };
    }
    setState(patch);
  } catch (err) {
    if (mine !== epoch) return;
    addMessage(patientId, { role: "assistant", kind: "error", text: errorText(err), mode });
    setState({
      sending: false,
      evidence: mode === "gk" ? state.evidence : { status: "error", chunks: [], error: errorText(err) },
    });
  }
}

async function openCitation(id) {
  const mine = epoch;
  setState({ activeChunk: { status: "loading", data: null, error: null } });
  try {
    const data = await api.getChunk(id);
    if (mine !== epoch) return;
    setState({ activeChunk: { status: "ready", data, error: null } });
  } catch (err) {
    if (mine !== epoch) return;
    setState({ activeChunk: { status: "error", data: null, error: errorText(err) } });
  }
}

function setMode(mode) {
  if (MODES[mode]) setState({ mode });
}

function setDemo(value) {
  api.setDemoState(value);
  const url = new URL(window.location.href);
  if (value === "ready") url.searchParams.delete("state");
  else url.searchParams.set("state", value);
  history.replaceState(null, "", url);
  setState({ demo: api.getDemoState(), messages: {}, timeline: [], evidence: { status: "idle", chunks: [], error: null } });
  loadPatients();
}

const actions = {
  selectPatient,
  openCitation,
  reload: () => setDemo(state.demo),
  retryLast: () => state.lastQuestion && sendQuestion(state.lastQuestion),
};

function render(s) {
  renderPatients(s, actions);
  renderPatientDetail(s, actions);
  renderChat(s, actions);
  renderEvidence(s, actions);
  renderTimeline(s);
  renderMode(s);
  document.getElementById("demo-state").value = s.demo;
}

function wireControls() {
  for (const input of document.querySelectorAll('input[name="source-mode"]')) {
    input.addEventListener("change", () => setMode(input.value));
  }
  const form = document.getElementById("chat-form");
  const field = document.getElementById("chat-input");
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const text = field.value.trim();
    if (!text) return;
    field.value = "";
    sendQuestion(text);
  });
  document.getElementById("demo-state").addEventListener("change", (e) => setDemo(e.target.value));
  document.getElementById("demo-reset").addEventListener("click", () => setDemo("ready"));
  document.getElementById("signin-button").addEventListener("click", (e) => e.preventDefault());

  // Footer legend: add the same icons used by the badges in the panels.
  for (const [kind, badge] of [["fact", ".prov-fact"], ["evidence", ".prov-evidence"], ["interpretation", ".prov-interpretation"]]) {
    document.querySelector(`.legend ${badge}`)?.prepend(icon(PROVENANCE[kind].icon));
  }
}

function showMockLabel() {
  // Always visible when mock patients are shown, so demo data is never mistaken for database data.
  const label = document.createElement("p");
  label.className = "mock-source-label";
  label.setAttribute("role", "status");
  label.textContent = "DEMO DATA (mock): patients are not coming from the database.";
  document.querySelector(".banner").after(label);
}

subscribe(render);
wireControls();
if (api.isMockSource()) showMockLabel();
const requested = new URLSearchParams(window.location.search).get("state") || "ready";
api.setDemoState(requested);
setState({ demo: api.getDemoState() });
loadPatients();
