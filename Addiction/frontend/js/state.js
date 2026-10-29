// Tiny observable store. Render modules read `state`; main.js changes it with setState().

const listeners = new Set();

export const state = {
  auth: { status: "loading", user: null }, // loading | signed-in | signed-out | mock
  authMessage: null, // friendly text shown after a failed sign-in
  demo: "ready", // ready | loading | empty | error | no-evidence
  mode: "rag", // gk | rag | both
  patients: { status: "loading", items: [], error: null }, // loading | ready | empty | error | signed-out
  selectedId: null,
  patient: { status: "idle", data: null, error: null }, // idle | loading | ready | error
  messages: {}, // { [patientId]: [{ role, text, citations?, mode?, kind?, answer? }] }
  sessions: {}, // { [patientId]: { id } }: the chat session in use for each patient (null id = start a new one)
  sending: false,
  sendingSince: null, // Date.now() of the question being answered (drives the elapsed-seconds counter)
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
