// Tiny observable store. Render modules read `state`; main.js changes it with setState().

const listeners = new Set();

export const state = {
  demo: "ready", // ready | loading | empty | error | no-evidence
  mode: "rag", // gk | rag | both
  patients: { status: "loading", items: [], error: null }, // loading | ready | empty | error
  selectedId: null,
  patient: { status: "idle", data: null, error: null }, // idle | loading | ready | error
  messages: {}, // { [patientId]: [{ role, text, citations?, mode?, kind? }] }
  sending: false,
  lastQuestion: null,
  evidence: { status: "idle", chunks: [], error: null }, // idle | ready | no-evidence | error
  activeChunk: { status: "idle", data: null, error: null }, // idle | loading | ready | error
  timeline: [],
};

export function setState(patch) {
  Object.assign(state, patch);
  listeners.forEach((listener) => listener(state));
}

export function subscribe(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function addMessage(patientId, message) {
  const existing = state.messages[patientId] || [];
  setState({ messages: { ...state.messages, [patientId]: [...existing, message] } });
}
