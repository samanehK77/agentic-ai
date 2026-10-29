// Where the API runs. The frontend is served on port 8000; the API uses 8001.
// Use the host name localhost for both: the login cookie belongs to one host name, so mixing
// localhost and 127.0.0.1 would break sign-in. Development only (plain HTTP), see docs/API_ACCESS_POLICY.md.
export const API_BASE_URL = "http://localhost:8001";

// How long the browser waits for one answer before giving up. It must be longer than the API's workflow limit
// (GRAPH_TOTAL_TIMEOUT_SECONDS, default 480 s): a local model can take several minutes.
export const ANSWER_TIMEOUT_MS = 540000;
