// Small DOM helpers. Text is always added as text nodes or textContent, never as HTML.

const SVG_NS = "http://www.w3.org/2000/svg";

export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === false || value == null) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key === "dataset") Object.assign(node.dataset, value);
    else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child == null || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

const ICONS = {
  fact: [["circle", { cx: 12, cy: 8, r: 4 }], ["path", { d: "M4 21c0-4.4 3.6-8 8-8s8 3.6 8 8" }]],
  evidence: [["path", { d: "M6 3h9l4 4v14H6z" }], ["path", { d: "M9 12h7M9 16h7" }]],
  interpretation: [["path", { d: "M4 5h16v11H9l-5 4z" }]],
  loading: [["path", { d: "M12 3a9 9 0 1 0 9 9" }]],
  empty: [["rect", { x: 4, y: 5, width: 16, height: 14, rx: 2 }], ["path", { d: "M4 13h5l1 2h4l1-2h5" }]],
  error: [["circle", { cx: 12, cy: 12, r: 9 }], ["path", { d: "M12 7v6M12 16.5v.5" }]],
  "no-evidence": [["circle", { cx: 11, cy: 11, r: 6 }], ["path", { d: "M20 20l-4.5-4.5M8.5 8.5l5 5" }]],
  retrieval: [["circle", { cx: 11, cy: 11, r: 6 }], ["path", { d: "M20 20l-4.5-4.5" }]],
  generation: [["path", { d: "M12 3l2.2 5.8L20 11l-5.8 2.2L12 19l-2.2-5.8L4 11l5.8-2.2z" }]],
  info: [["circle", { cx: 12, cy: 12, r: 9 }], ["path", { d: "M12 11v6M12 7.5v.5" }]],
};

export function icon(name) {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("class", `icon icon-${name}`);
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  for (const [tag, attrs] of ICONS[name] || ICONS.info) {
    const part = document.createElementNS(SVG_NS, tag);
    for (const [k, v] of Object.entries(attrs)) part.setAttribute(k, v);
    svg.append(part);
  }
  return svg;
}

// Three kinds of content, always distinguished by color AND icon AND text label.
export const PROVENANCE = {
  fact: { label: "Patient fact (synthetic)", icon: "fact" },
  evidence: { label: "Research evidence (MOCK)", icon: "evidence" },
  interpretation: { label: "Model interpretation (mock)", icon: "interpretation" },
};

// `label` replaces the default text, e.g. real retrieved evidence is not "(MOCK)".
export function provenanceBadge(kind, label) {
  const info = PROVENANCE[kind];
  return el("span", { class: `badge prov-${kind}` }, icon(info.icon), el("span", { text: label || info.label }));
}

export function formatTime(iso) {
  const date = new Date(iso);
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}
