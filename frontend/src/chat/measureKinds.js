/* What each measure column IS (audit 2026-10-29, section G). A copy of
   app/measure_kinds.json — tests/test_chat_ui_audit_totals_2026_10_29.py fails
   when the two differ. Edit both together. */
export const MEASURE_KINDS = {
  "rate": ["pct", "percent", "percentage", "perc", "%", "share", "rate", "ratio", "avg", "average", "mean", "median",
           "per", "min", "max", "minimum", "maximum", "participation", "growth", "yoy", "utilisation",
           "utilization", "efficiency"],
  "stock": ["card", "cards", "jobcard", "jobcards", "cumulative", "todate"],
  "flow": ["day", "days", "mandays", "persondays", "exp", "expenditure", "amount", "amt", "money", "crore", "cr",
           "lakh", "lakhs", "rupees", "rs", "inr", "wage", "wages", "paid", "released", "disbursed", "spent", "cost",
           "payments", "transactions"],
  "distinct": ["village", "villages", "household", "households", "hh", "beneficiary", "beneficiaries", "member",
               "members", "people", "persons", "worker", "workers", "farmer", "farmers", "pg", "pgs", "groups",
               "applicant", "applicants"]
};
