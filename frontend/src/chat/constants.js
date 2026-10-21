/* Static content of the chat console: sample questions, UI strings, the scheme
   overview cards, glossary and use cases. Moved verbatim from web/ai_query.html. */

// One unified assistant. Scheme selection happens server-side inside the
// pipeline — there are no scheme buttons.
export const UNIFIED_SAMPLES = [
  { ico: '📅', text: 'Total MGNREGA person-days in 2023-24' },
  { ico: '💳', text: 'Job cards issued in 2025-26' },
  { ico: '🏠', text: 'PMAY-G houses completed by district' },
  { ico: '💰', text: 'Total PMAY-G amount released in 2024-25' },
  { ico: '🌾', text: 'How many FOCUS+ payments were made in each batch' },
  { ico: '📍', text: 'FOCUS+ payments by district' },
  { ico: '🚀', text: 'How many CM Elevate applications are on hold?' },
  { ico: '📊', text: 'Top 5 CM Elevate schemes by applications' },
];

// UI chrome strings, keyed by language. `en` is authoritative; `kha` (Khasi) and
// `gar` (Garo) repeat the English until real translations are dropped in. The
// sample prompts are deliberately NOT translated: their text is sent verbatim
// to the NL-to-SQL backend. Only the model's ANSWER switches language (the
// `language` field on /api/query).
const EN = {
  heroTitle: 'What would you like to know?',
  heroSub: "Ask about Meghalaya's MGNREGA, PMAY-G, FOCUS+, CM Elevate, Focus Legacy and CM Elevate Legacy — data questions and how the schemes work.",
  promptsTitle: 'Try a question',
  composerPh: 'Ask me something…',
  sendBtn: 'Send',
  micBtn: 'Speak',
};
export const UI_STRINGS = {
  en: EN,
  kha: { ...EN },   // TODO(translation): replace with Khasi copy.
  gar: { ...EN },   // TODO(translation): replace with Garo copy.
};
// Code labels and full names (#235): the name is shown beside the code so an
// officer who does not recognise "KHA" or "GAR" still finds their language.
export const LANGS = [
  { code: 'en', label: 'EN', name: 'English' },
  { code: 'kha', label: 'KHA', name: 'Khasi' },
  { code: 'gar', label: 'GAR', name: 'Garo' },
];

// Qwen3-ASR expects bare ISO-639-1 codes; Khasi and Garo are outside its
// language set, so both are transcribed as English.
export const VOICE_LANG = { en: 'en', kha: 'en', gar: 'en' };

// Scheme overview cards. The `stats` are FALLBACKS only: the welcome card replaces them
// with live figures from GET /api/scheme-stats (computed from megh_db), so the cards follow
// every data refresh. Keep these close to the data anyway — last synced 2026-10-15.
// ORDER MATTERS — oldest scheme first, newest last: the
// carousel pages this list in order, so a new scheme goes at the END.
export const SCHEME_CARDS = [
  {
    key: 'mgnrega', cls: 'focus-card', ico: '🧑‍🌾', name: 'MGNREGA',
    meta: 'Rural employment guarantee · village-year grain · FY 2022-23 to 2025-26',
    stats: [['9.09 Cr', 'Person-days (4 yr)'], ['₹3,628.67 Cr', 'Expenditure (4 yr)'], ['6,491', 'Villages with activity']],
  },
  {
    key: 'pmay_g', cls: 'unified-card', ico: '🏠', name: 'PMAY-G',
    meta: 'Rural housing · one row per sanctioned house · sanctions FY 2017-18 to 2023-24',
    stats: [['1,70,981', 'Houses sanctioned'], ['1,29,941', 'Houses completed'], ['₹2,185.26 Cr', 'Funds released']],
  },
  {
    key: 'focus_plus', cls: 'elevate-card', ico: '🌾', name: 'FOCUS+',
    meta: 'Meghalaya farmer cash benefit (DBT) · one row per disbursement · FY 2022-23 & 2025-26 · figures provisional',
    stats: [['3,85,671', 'Disbursements'], ['₹119.74 Cr*', 'Amount disbursed*'], ['12', 'Districts covered']],
  },
  {
    key: 'cm_elevate', cls: 'cmelevate-card', ico: '🚀', name: 'CM Elevate',
    meta: 'Entrepreneurship & livelihood programme · one row per application across 15 schemes · no date/amount data',
    stats: [['8,867', 'Applications'], ['15', 'Schemes'], ['12', 'Districts covered']],
  },
  {
    key: 'focus_legacy', cls: 'focus-card', ico: '🤝', name: 'Focus Legacy',
    meta: 'Meghalaya producer-group scheme (original FOCUS) · one row per payment to a PG · FY 2021-22 to 2025-26, no FY 2023-24 · figures provisional',
    stats: [['11,906', 'Producer Groups'], ['1,02,021', 'Memberships paid'], ['₹51.01 Cr*', 'Amount remitted*']],
  },
  {
    key: 'cm_elevate_legacy', cls: 'cmelevate-card', ico: '💼', name: 'CM Elevate Legacy',
    meta: 'CM-ELEVATE sanctions & disbursements · one row per sanctioned applicant across 13 schemes · FY 2024-25 & 2025-26 · figures provisional',
    stats: [['2,823', 'Sanction records'], ['13', 'Schemes'], ['₹82.90 Cr*', 'Disbursed (subsidy + loan)*']],
  },
];

// Each scheme's own questions, shown when a carousel page holds that scheme alone.
export const CARD_QUESTIONS = {
  mgnrega: {
    title: 'Try an MGNREGA question',
    items: [
      { ico: '📅', text: 'Total MGNREGA person-days in 2023-24' },
      { ico: '💳', text: 'Job cards issued in 2025-26' },
      { ico: '💰', text: 'MGNREGA expenditure by district' },
      { ico: '📊', text: 'Top 5 blocks by MGNREGA person-days' },
      { ico: '🏘️', text: 'How many villages had MGNREGA activity?' },
      { ico: '📖', text: 'Who is eligible for MGNREGA work?' },
    ],
  },
  pmay_g: {
    title: 'Try a PMAY-G question',
    items: [
      { ico: '🏠', text: 'PMAY-G houses completed by district' },
      { ico: '💰', text: 'Total PMAY-G amount released in 2024-25' },
      { ico: '🧱', text: 'How many PMAY-G houses were sanctioned?' },
      { ico: '📊', text: 'Top 5 districts by PMAY-G completion' },
      { ico: '⏳', text: 'How many PMAY-G houses are still incomplete?' },
      { ico: '📖', text: 'Who is eligible for a PMAY-G house?' },
    ],
  },
  focus_legacy: {
    title: 'Try a Focus Legacy (Producer Group) question',
    items: [
      { ico: '🤝', text: 'How many producer groups were paid under Focus Legacy?' },
      { ico: '👥', text: 'How many PG members were covered under Focus Legacy?' },
      { ico: '💰', text: 'Total Focus Legacy amount disbursed by district' },
      { ico: '🌾', text: 'Which products do Focus Legacy producer groups work on?' },
      { ico: '🏦', text: 'Which banks handle Focus Legacy payments?' },
      { ico: '📖', text: 'What is the main objective of FOCUS?' },
    ],
  },
  focus_plus: {
    title: 'Try a FOCUS+ question',
    items: [
      { ico: '👥', text: 'How many FOCUS+ beneficiaries are there?' },
      { ico: '📊', text: 'Top 5 districts by FOCUS+ beneficiaries' },
      { ico: '🏦', text: 'Which bank serves the most FOCUS+ beneficiaries?' },
      { ico: '📍', text: 'How many beneficiaries in West Garo Hills?' },
      { ico: '💰', text: 'What is the total amount paid out?' },
    ],
  },
  cm_elevate: {
    title: 'Try a CM Elevate question',
    items: [
      { ico: '📝', text: 'How many CM Elevate applications are there?' },
      { ico: '⏸️', text: 'How many CM Elevate applications are on hold?' },
      { ico: '📊', text: 'Top 5 CM Elevate schemes by applications' },
      { ico: '🚻', text: 'What is the gender split of CM Elevate applicants?' },
      { ico: '📍', text: 'CM Elevate applications by district' },
      { ico: '✅', text: 'Show the verification status breakdown for CM Elevate' },
    ],
  },
  cm_elevate_legacy: {
    title: 'Try a CM Elevate Legacy (sanctions & disbursements) question',
    items: [
      { ico: '💰', text: 'What is the total amount disbursed under CM Elevate Legacy?' },
      { ico: '📍', text: 'CM Elevate Legacy disbursement by district' },
      { ico: '📊', text: 'CM Elevate Legacy records by scheme' },
      { ico: '🏦', text: 'CM Elevate Legacy loans by lender' },
      { ico: '📅', text: 'CM Elevate Legacy records by financial year' },
      { ico: '📈', text: 'How much of the sanctioned amount has been disbursed under CM Elevate Legacy?' },
    ],
  },
};

export const GLOSSARY = {
  'MGNREGA': [
    { term: 'Person-days', def: 'The headline output measure — one person working one day. Additive; always SUM.' },
    { term: 'Expenditure', def: 'Wage + material + tax spend, in LAKH rupees (divide by 100 for crore).' },
    { term: 'Job cards (stock)', def: 'Cumulative count — never summed across years; reported one year at a time.' },
    { term: '100-day completion', def: 'Households that got the full 100 days of guaranteed work in a financial year.' },
    { term: 'Wage-share (60:40)', def: 'unskilled_wage ÷ total_exp — the statutory Schedule-I ratio.' },
  ],
  'PMAY-G': [
    { term: 'Sanctioned amount', def: 'Assistance approved per house, in RUPEES — effectively a per-house constant.' },
    { term: 'Amount released', def: 'Money actually disbursed against the sanction, in RUPEES — the figure that varies.' },
    { term: 'Completed / in progress', def: 'Construction stage — read from the is_completed / is_in_progress flags.' },
    { term: 'Placeholder row', def: 'Not a real house — excluded from every count and sum unless the question is about data completeness.' },
  ],
  'FOCUS+': [
    { term: 'Disbursement', def: 'One row = one payment to one member in one tranche. COUNT(*) is a payment count, not a person count.' },
    { term: 'Batch (93K / 12.5K)', def: 'Two cohorts stacked in one table: 93K legacy paid (4 rows/person, no personal fields) and 12.5K newer registrations (1 row/person, gender/occupation/status populated).' },
    { term: 'Beneficiaries', def: 'Three different numbers — payments, members with an id (12.5K only, ~12,527), and the legacy count (~93,286, not derivable from the database). Always shown side by side, labelled.' },
    { term: 'Amount disbursed', def: 'The only money measure. Unit is UNVERIFIED — read from dim_scheme, never assumed. Only two values exist: 5,000 and 2,500.' },
    { term: 'Tranche', def: 'A payment round label (Tranch 1..4) — categorical, never a time series. There is no date column.' },
  ],
};

export const USE_CASES = {
  'MGNREGA': [
    'Total MGNREGA person-days in 2023-24',
    'MGNREGA wage expenditure by district in 2024-25',
    'Households that completed 100 days in West Khasi Hills',
    'Cost per person-day by district in 2025-26',
  ],
  'PMAY-G': [
    'PMAY-G houses completed by district',
    'PMAY-G houses sanctioned vs completed in East Garo Hills',
    'Total PMAY-G amount released in 2024-25',
    'Who is eligible for PMAY-G?',
  ],
  'FOCUS+': [
    'How many FOCUS+ payments were made in each batch',
    'FOCUS+ payments by district',
    'How much has been disbursed under FOCUS+',
    'What is FOCUS+ and who is eligible?',
  ],
  'Cross-scheme': [
    'Compare MGNREGA vs PMAY-G spend in West Khasi Hills',
    'Which villages have both MGNREGA activity and PMAY-G houses?',
  ],
};

// Mirrors app/deps.py require_admin: the roles the /admin/* API accepts.
export const ADMIN_ROLES = ['admin', 'tenant_admin', 'super_admin'];
