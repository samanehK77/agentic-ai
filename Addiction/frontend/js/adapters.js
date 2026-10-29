// Turns API JSON into the shapes the UI already uses (see docs/FRONTEND_INTEGRATION_PLAN.md).
// Pure functions: no network, no DOM.

const GENDER_LABELS = { woman: "Woman", man: "Man", non_binary: "Non-binary", other: "Other", unknown: "Unknown" };
const CATEGORY_LABELS = { alcohol: "Alcohol", cannabis: "Cannabis", opioids: "Opioids", stimulants: "Stimulants" };
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

const words = (value) => {
  const text = String(value).replaceAll("_", " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
};

export function categoryLabel(primaryCategory, subject) {
  if (primaryCategory === "behavioral") return `Behavioral: ${subject || "unknown"}`;
  return CATEGORY_LABELS[primaryCategory] || words(primaryCategory);
}

// "2012-09-01" + precision -> "2012" | "Sep 2012" | "1 Sep 2012". Parsed by hand to avoid time-zone shifts.
export function formatDate(isoDate, precision = "day") {
  const [year, month, day] = isoDate.split("-").map(Number);
  if (precision === "year") return String(year);
  if (precision === "month") return `${MONTHS[month - 1]} ${year}`;
  return `${day} ${MONTHS[month - 1]} ${year}`;
}

export function patientListItem(api) {
  return {
    id: api.patient_id,
    age: api.age_at_intake,
    sex: GENDER_LABELS[api.gender] || words(api.gender),
    category: categoryLabel(api.primary_category, api.primary_use_subject),
    summary: api.history_summary,
    treatment_summary: api.treatment_summary,
  };
}

export function patientDetail(profile, historyItems) {
  const latest = [...profile.progress].sort((a, b) => a.observed_on.localeCompare(b.observed_on)).at(-1);
  const factors = (kind) => profile.factors.filter((f) => f.kind === kind).map((f) => f.description);

  return {
    ...patientListItem(profile),
    background: profile.background,
    behaviors: factors("observed_behavior"),
    history: historyItems
      .filter((item) => item.source === "history")
      .map((item) => ({ period: formatDate(item.event_date, item.date_precision || "day"), event: item.summary })),
    triggers: factors("trigger"),
    previous_interventions: profile.interventions.map((i) => ({
      name: `${words(i.type)} (${i.setting})`,
      period: `${formatDate(i.start_date)} to ${i.end_date ? formatDate(i.end_date) : "ongoing"}`,
      outcome: i.reported_outcome,
    })),
    progress: latest
      ? { status: `${words(latest.use_status)}, motivation: ${latest.motivation.replaceAll("_", " ")}`, note: latest.note }
      : { status: "No observations recorded", note: "" },
  };
}

// One hit of POST /api/retrieval/search -> the shape the Evidence Inspector uses.
// citation_id is the real chunk id, so a citation can only ever point to a retrieved chunk.
export function evidenceChunk(hit) {
  const pages = hit.page_start === hit.page_end ? String(hit.page_start) : `${hit.page_start}-${hit.page_end}`;
  return {
    citation_id: hit.chunk_id,
    document: hit.title,
    section: hit.section_title || "(no section title)",
    page: pages,
    text: hit.text,
    score: hit.similarity, // cosine similarity: a score, not a probability
    section_type: hit.section_type,
    possible_injection: hit.possible_injection === true,
    real: true,
  };
}
