// Activity timeline: retrieval and generation events (real retrieval since Batch 06; generation is still a placeholder).
import { el, icon, formatTime } from "./dom.js";
import { stateBlock } from "./states.js";

export function renderTimeline(state) {
  const container = document.getElementById("timeline-body");

  if (state.demo === "loading") return container.replaceChildren(stateBlock("loading", { title: "Loading activity…" }));
  if (state.timeline.length === 0) {
    return container.replaceChildren(stateBlock("empty", {
      title: "No activity yet",
      message: "Ask a question to see retrieval and generation events.",
    }));
  }

  container.replaceChildren(
    el("ol", { class: "timeline", "aria-label": "Activity events" },
      state.timeline.map((evt) =>
        el("li", { class: `timeline-item timeline-${evt.type} timeline-status-${evt.status || "ok"}` },
          el("span", { class: "timeline-icon" }, icon(evt.type)),
          el("span", { class: "timeline-body" },
            el("span", { class: "timeline-label", text: evt.label }),
            evt.status && evt.status !== "ok" && el("span", { class: "timeline-chip", text: evt.status }),
            evt.detail && el("span", { class: "timeline-detail", text: ` · ${evt.detail}` }),
            el("span", { class: "timeline-meta" }, `${evt.patient_id} · `, el("time", { datetime: evt.time, text: formatTime(evt.time) })),
          ),
        ))),
  );
}
