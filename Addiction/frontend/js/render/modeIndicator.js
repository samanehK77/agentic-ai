// Source-mode indicator: syncs the radio group and the visible pills with the current mode.
import { MODES } from "../../data/mock-data.js";

export function renderMode(state) {
  const mode = MODES[state.mode];
  for (const input of document.querySelectorAll('input[name="source-mode"]')) {
    input.checked = input.value === state.mode;
  }
  for (const pill of document.querySelectorAll("[data-mode-pill]")) {
    pill.textContent = `Source mode: ${mode.label}`;
    pill.dataset.mode = state.mode;
  }
  document.getElementById("mode-description").textContent = mode.description;
}
