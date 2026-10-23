// MOCK DATA ONLY. Every patient below is fictional and synthetic.
// Every document excerpt is invented placeholder text and is NOT taken from,
// or attributed to, any real document (WHO, NIDA, Cochrane or otherwise).
// Field names mirror the future database (patient ids, chunk fields).

export const SYNTHETIC_NOTICE = "Synthetic data · Educational use only · Not clinical advice";

export const MODES = {
  gk: { value: "gk", label: "General Knowledge", description: "Answer without retrieved documents." },
  rag: { value: "rag", label: "RAG", description: "Answer from retrieved document excerpts." },
  both: { value: "both", label: "Both", description: "General knowledge plus retrieved excerpts." },
};

export const PATIENTS = [
  {
    id: "P-001",
    age: 46,
    sex: "Male",
    category: "Alcohol",
    summary: "Long-standing heavy drinking that began around work stress; two earlier attempts to cut down.",
    treatment_summary: "Outpatient counseling (2022), mutual-help group attendance, one inpatient stay (2023).",
    background: "Fictional warehouse supervisor, married, two adult children, lives in a mid-sized town.",
    behaviors: ["Drinks most evenings", "Hides empty bottles", "Missed several shifts in the past year"],
    history: [
      { period: "2012", event: "Drinking increases after a promotion." },
      { period: "2019", event: "First conversation with a family doctor about alcohol." },
      { period: "2023", event: "Inpatient stay after a workplace incident." },
    ],
    triggers: ["Late shifts", "Conflict with a manager", "Evenings alone"],
    previous_interventions: [
      { name: "Outpatient counseling", period: "2022", outcome: "Attended 8 of 12 sessions." },
      { name: "Mutual-help group", period: "2023-ongoing", outcome: "Attends irregularly." },
    ],
    progress: { status: "In early recovery", note: "Reports 41 days without drinking at last check-in." },
  },
  {
    id: "P-002",
    age: 29,
    sex: "Female",
    category: "Alcohol",
    summary: "Binge drinking at weekends since university; occasional blackouts and one driving incident.",
    treatment_summary: "Brief advice from a campus clinic (2021). No specialist treatment so far.",
    background: "Fictional graphic designer, shares a flat, active social life centered on bars and events.",
    behaviors: ["Heavy weekend drinking", "Drinks faster than friends", "Skips Monday work after big nights"],
    history: [
      { period: "2015", event: "Starts regular weekend drinking at university." },
      { period: "2021", event: "Brief intervention at a campus clinic." },
      { period: "2024", event: "Driving incident leads to a warning." },
    ],
    triggers: ["Social events", "Celebrations", "Deadline stress"],
    previous_interventions: [{ name: "Brief advice", period: "2021", outcome: "Reduced drinking for two months." }],
    progress: { status: "Ambivalent", note: "Considering whether to change; has not set a goal." },
  },
  {
    id: "P-003",
    age: 34,
    sex: "Male",
    category: "Cannabis",
    summary: "Daily cannabis use for about ten years; difficulty sleeping without it and low motivation at work.",
    treatment_summary: "Two failed attempts to stop on his own; one counseling intake (2024).",
    background: "Fictional freelance video editor, lives alone, works irregular hours.",
    behaviors: ["Uses several times a day", "Spends much of income on cannabis", "Withdraws from friends who do not use"],
    history: [
      { period: "2014", event: "Daily use begins." },
      { period: "2020", event: "First serious attempt to stop lasts nine days." },
      { period: "2024", event: "Attends an intake appointment at a counseling service." },
    ],
    triggers: ["Insomnia", "Boredom", "Being alone in the evening"],
    previous_interventions: [{ name: "Counseling intake", period: "2024", outcome: "Did not return for follow-up." }],
    progress: { status: "Contemplating change", note: "Has booked a second appointment." },
  },
  {
    id: "P-004",
    age: 51,
    sex: "Female",
    category: "Opioids",
    summary: "Dependence on prescription opioids that began after a back injury; rising doses over several years.",
    treatment_summary: "Supervised medication-based treatment since 2022; regular clinic visits.",
    background: "Fictional former nurse, divorced, receives disability support.",
    behaviors: ["Attends clinic appointments reliably", "Worries about pain returning", "Keeps a daily routine"],
    history: [
      { period: "2015", event: "Back injury and first opioid prescription." },
      { period: "2020", event: "Doses rise; early refill requests." },
      { period: "2022", event: "Enters a supervised treatment program." },
    ],
    triggers: ["Pain flare-ups", "Poor sleep", "Isolation at weekends"],
    previous_interventions: [
      { name: "Supervised medication program", period: "2022-ongoing", outcome: "Stable attendance." },
      { name: "Pain-management program", period: "2023", outcome: "Completed." },
    ],
    progress: { status: "Stable", note: "No missed appointments in 12 months." },
  },
  {
    id: "P-005",
    age: 24,
    sex: "Male",
    category: "Opioids",
    summary: "Early-stage opioid problem after non-prescribed pill use at parties; recently started using more often.",
    treatment_summary: "No treatment yet; one emergency visit (2025). Referral offered.",
    background: "Fictional part-time barista and student, lives with roommates.",
    behaviors: ["Uses pills with friends", "Borrows money", "Hides use from family"],
    history: [
      { period: "2023", event: "First non-prescribed pill use." },
      { period: "2025", event: "Emergency visit after a scare." },
    ],
    triggers: ["Parties", "Friends who use", "Financial stress"],
    previous_interventions: [{ name: "Emergency-department referral", period: "2025", outcome: "Not yet acted on." }],
    progress: { status: "Pre-treatment", note: "Open to talking, has not started care." },
  },
  {
    id: "P-006",
    age: 38,
    sex: "Male",
    category: "Stimulants",
    summary: "Methamphetamine use for six years, with repeated cycles of heavy use and exhaustion.",
    treatment_summary: "Residential program (2022) and outpatient behavioral therapy (2024); relapsed after both.",
    background: "Fictional construction worker, separated, sees his daughter on weekends.",
    behaviors: ["Goes days with little sleep", "Weight loss", "Irritable when tired"],
    history: [
      { period: "2019", event: "Begins using methamphetamine." },
      { period: "2022", event: "Completes a residential program." },
      { period: "2024", event: "Relapse after leaving a job." },
    ],
    triggers: ["Unemployment", "Contact with former using friends", "Fatigue"],
    previous_interventions: [
      { name: "Residential program", period: "2022", outcome: "Completed; relapsed after 4 months." },
      { name: "Behavioral therapy", period: "2024", outcome: "Dropped out after 6 sessions." },
    ],
    progress: { status: "Recently relapsed", note: "Re-engaging with a counselor." },
  },
  {
    id: "P-007",
    age: 31,
    sex: "Female",
    category: "Stimulants",
    summary: "Cocaine use mainly at nightlife venues; use has grown from monthly to weekly over two years.",
    treatment_summary: "One assessment visit (2025); considering outpatient care.",
    background: "Fictional bartender and event organizer, works nights.",
    behaviors: ["Weekly use", "Spends heavily on nights out", "Feels low after use"],
    history: [
      { period: "2021", event: "Occasional use at work events." },
      { period: "2025", event: "Assessment visit at a community clinic." },
    ],
    triggers: ["Nightlife environment", "Late nights", "Co-workers who use"],
    previous_interventions: [{ name: "Assessment visit", period: "2025", outcome: "Given information; no follow-up yet." }],
    progress: { status: "Considering options", note: "Discussing a job change." },
  },
  {
    id: "P-008",
    age: 42,
    sex: "Male",
    category: "Behavioral: gambling",
    summary: "Online sports betting that escalated after a large win; significant debts and secrecy from family.",
    treatment_summary: "Self-exclusion on two platforms (2024); started counseling for gambling (2025).",
    background: "Fictional accountant, married, mortgage and credit-card debt.",
    behaviors: ["Checks betting apps constantly", "Chases losses", "Hides statements from spouse"],
    history: [
      { period: "2020", event: "Large early win; betting increases." },
      { period: "2023", event: "Debts discovered by spouse." },
      { period: "2025", event: "Starts counseling." },
    ],
    triggers: ["Live sports events", "Payday", "Stress at work"],
    previous_interventions: [
      { name: "Platform self-exclusion", period: "2024", outcome: "Moved to a third platform." },
      { name: "Gambling counseling", period: "2025-ongoing", outcome: "Attending weekly." },
    ],
    progress: { status: "Engaged in treatment", note: "Three weeks without betting." },
  },
  {
    id: "P-009",
    age: 22,
    sex: "Male",
    category: "Behavioral: gaming",
    summary: "Gaming for 10-12 hours a day; dropped classes and sleeps during the day.",
    treatment_summary: "School counselor meetings (2025); family sessions planned.",
    background: "Fictional university student living with his parents.",
    behaviors: ["Plays through the night", "Skips meals", "Irritable when interrupted"],
    history: [
      { period: "2022", event: "Playing time increases during the pandemic." },
      { period: "2025", event: "Fails two courses; meets a school counselor." },
    ],
    triggers: ["Online team commitments", "Academic pressure", "Loneliness"],
    previous_interventions: [{ name: "School counselor meetings", period: "2025", outcome: "Attended 3 meetings." }],
    progress: { status: "Early engagement", note: "Agreed to a family session." },
  },
  {
    id: "P-010",
    age: 57,
    sex: "Female",
    category: "Cannabis",
    summary: "Cannabis use started for pain and sleep; now uses throughout the day and feels unable to stop.",
    treatment_summary: "Discussed with her family doctor (2024); enrolled in a brief outpatient group (2025).",
    background: "Fictional retired teacher, widowed, close to her grandchildren.",
    behaviors: ["Uses morning and evening", "Worried about driving", "Hides use from family"],
    history: [
      { period: "2019", event: "Starts using for pain after surgery." },
      { period: "2024", event: "Talks to her doctor about cutting down." },
      { period: "2025", event: "Joins an outpatient group." },
    ],
    triggers: ["Chronic pain", "Poor sleep", "Grief anniversaries"],
    previous_interventions: [{ name: "Outpatient group", period: "2025-ongoing", outcome: "Attends regularly." }],
    progress: { status: "Making gradual progress", note: "Using less often than three months ago." },
  },
];

// Mock retrieved chunks. Shape matches the future database:
// document, section, page, citation_id (plus text and a mock score).
export const CHUNKS = [
  { citation_id: "MOCK-C01", document: "MOCK Document A: Placeholder Guideline", section: "2.1 Screening and assessment", page: 14, score: 0.91,
    text: "MOCK excerpt. Placeholder text standing in for a retrieved passage about screening and assessment. It contains no real research content." },
  { citation_id: "MOCK-C02", document: "MOCK Document A: Placeholder Guideline", section: "3.2 Psychosocial approaches", page: 27, score: 0.87,
    text: "MOCK excerpt. Placeholder text standing in for a retrieved passage about psychosocial approaches. It is invented for layout testing." },
  { citation_id: "MOCK-C03", document: "MOCK Document B: Placeholder Handbook", section: "Chapter 4: Retention in care", page: 61, score: 0.83,
    text: "MOCK excerpt. Placeholder text standing in for a retrieved passage about staying engaged in care. No real source is represented." },
  { citation_id: "MOCK-C04", document: "MOCK Document B: Placeholder Handbook", section: "Chapter 6: Co-occurring problems", page: 92, score: 0.79,
    text: "MOCK excerpt. Placeholder text standing in for a retrieved passage about co-occurring problems. It is not a real citation." },
  { citation_id: "MOCK-C05", document: "MOCK Document C: Placeholder Review", section: "Results: Overview", page: 8, score: 0.74,
    text: "MOCK excerpt. Placeholder text standing in for a retrieved passage summarising review results. It reports no real findings." },
  { citation_id: "MOCK-C06", document: "MOCK Document C: Placeholder Review", section: "Discussion: Limitations", page: 19, score: 0.7,
    text: "MOCK excerpt. Placeholder text standing in for a retrieved passage about limitations of evidence. Invented for demonstration only." },
];

// Fixed replies. They depend only on the selected mode and give no treatment advice.
export const REPLIES = {
  gk: {
    text: "MOCK reply (General Knowledge mode). This fixed response is shown for layout testing only. It is not produced by a model, uses no retrieved documents, and gives no treatment advice.",
    citations: [],
  },
  rag: {
    text: "MOCK reply (RAG mode). This fixed response points only to mock excerpts. Select a citation to inspect the excerpt. It gives no treatment advice.",
    citations: ["MOCK-C01", "MOCK-C02", "MOCK-C03"],
  },
  both: {
    text: "MOCK reply (Both mode). This fixed response combines a general-knowledge placeholder with mock excerpts, and gives no treatment advice. Select a citation to inspect the excerpt.",
    citations: ["MOCK-C01", "MOCK-C04"],
  },
  noEvidence: {
    text: "MOCK reply: no supporting evidence was found in the mock corpus for this question, so nothing is cited. A real answer must say this plainly and must not invent sources.",
    citations: [],
  },
};

// Mock timeline templates: each question appends these events.
export const TIMELINE_STEPS = {
  gk: [
    { type: "info", label: "Question received" },
    { type: "info", label: "Retrieval skipped (General Knowledge mode)" },
    { type: "generation", label: "Generation started" },
    { type: "generation", label: "Answer ready" },
  ],
  rag: [
    { type: "info", label: "Question received" },
    { type: "retrieval", label: "Retrieval started" },
    { type: "retrieval", label: "Chunks retrieved" },
    { type: "generation", label: "Generation started" },
    { type: "generation", label: "Answer ready" },
  ],
};
