# Role-Based Access Control (RBAC) — Implementation Report

**Date:** 2026-10-26 · **Branch:** `update/2026-10-24` · **Method:** code review only (no live calls, no code changed).
Labels: **VERIFIED** = read in code/config/tests · **INFERRED** = reasoned from code, not run.

---

## 1. Summary

| Question | Answer |
|---|---|
| How many roles exist? | **8**, defined in `app/auth.py` `ROLE_PERMISSIONS` |
| How many of them are usable today? | **7**. `public` is defined but no request can ever receive it (§3) |
| What does a role control? | (a) which **API endpoints** a user can call; (b) which **data** a question can return, on 3 axes: **scheme**, **geography** (district/block), **granularity** (state < district < block < village); (c) which **tenant's** admin data they can see |
| Where is it enforced? | Application layer only (FastAPI dependencies + `auth.authorize` on the SQL). There is no database-level enforcement (no row-level security; the app still connects as `postgres`, KI-304) |
| Is it implemented? | **Mostly, yes.** Login, JWT, endpoint gates, tenant isolation, the 3 data checks, re-checking of repaired SQL, a scope-aware cache and an audit trail all work. |
| What is missing or broken? | **1 high-severity privilege escalation** in user editing, **4 answer paths that skip the data check**, 1 unscoped stats endpoint, 2 known column blind spots (KI-007), 2 fail-open defaults, and **no tests for the admin and role endpoints** (§6) |

**Rough completeness:** about **75–80 %** of a working RBAC is built. The design is complete. The gaps are holes in enforcement, not missing features.

---

## 2. The roles (VERIFIED, `app/auth.py:43-95`)

| # | Role | Tier | Finest data level | Geography | Schemes | Admin API | Cross-tenant | In admin UI dropdown |
|---|---|---|---|---|---|---|---|---|
| 1 | `super_admin` | Admin | village | all | all 6 | yes | **yes** | yes |
| 2 | `tenant_admin` | Admin | village | all | all 6 | yes (own tenant) | no | hidden |
| 3 | `admin` | Admin | village | all | all 6 | yes (own tenant) | no | hidden |
| 4 | `state_officer` | Officer | **district** | all | all 6 | no | no | yes |
| 5 | `district_officer` | Officer | **block** | **pinned districts** | all 6 | no | no | yes |
| 6 | `block_officer` | Officer | village | **pinned districts/blocks** | all 6 | no | no | yes |
| 7 | `analyst` | Viewer | village | all | all 6 | no | no | hidden |
| 8 | `public` | Anonymous | **state** | all | all 6 | no | no | hidden |

Notes:
- `admin` and `tenant_admin` have identical permissions. One of them is redundant.
- Per user, an admin can set `districts`, `blocks`, `schemes` and `granularity_cap` (`app.users` table). The role sets the default and the per-user lists narrow it. The exception is `granularity_cap`, which can *widen* it (§6, KI-421).
- All 8 roles currently allow all 6 schemes. Scheme restriction exists only through the per-user `schemes` list.
- Admin roles **bypass all three data checks** by design (`auth.py:235`).
- Seeded accounts (`app/users.yaml`, KI-023): 5 users, one each of `super_admin`, `tenant_admin`, `state_officer`, `district_officer` (West Garo Hills) and `analyst`.
- The frontend hides the admin link and admin panels from non-admins (`ADMIN_ROLES` in `frontend/src/chat/constants.js`, `AdminApp.jsx`). The server enforces the same rule, so hiding them is only cosmetic.

---

## 3. Layer 1 — Authentication (VERIFIED)

| Feature | Status | Where |
|---|---|---|
| Username + password login; passwords hashed | ✅ Done | `routers/auth.py:35`, `security.py` |
| JWT (HS256, 12 h TTL); startup warns on a default or short secret | ✅ Done | `config.py:494-517, 647-659` |
| User record re-read from DB on **every** request, so a role change or deactivation applies at once | ✅ Done | `deps.py:41-44` |
| Login / logout / failed-login events logged | ✅ Done | `appdb.log_login` |
| One-time `super_admin` bootstrap (only when no users exist, or with `ADMIN_TOKEN`) | ✅ Done | `routers/auth.py:95` |
| `AUTH_ENABLED=true` in `.env` | ✅ On | `.env` |
| Token revocation / server-side logout | ❌ Not built (KI-016, accepted) | — |
| `public` role for anonymous callers | ⚠️ Dead code. Anonymous callers get `AUTH_DEFAULT_ROLE` (`analyst`), and every data endpoint then returns 401 | `deps.py:32-36` |

---

## 4. Layer 2 — Endpoint gates (VERIFIED)

There are 4 dependency gates in `app/deps.py`: `current_scope`, `require_user`, `require_admin`, `require_super`. `query.py`, `rag.py` and `stats.py` each keep a local copy of `require_user`.

| Access level | Count | Endpoints |
|---|---|---|
| Open | 2 (+2 limited) | `POST /api/auth/login`, `POST /api/auth/bootstrap` (self-closing); `/health` and `/metrics` show detail only with an admin JWT or the metrics token |
| Logged-in user | 14 | `/api/query`, `/api/query/stream`, `/api/query/transcribe`, `/api/history` (6 routes, filtered to the caller's own `user_id`), `/api/feedback`, `/api/auth/me`, `/api/auth/logout`, `/api/rag/status`, `/api/scheme-stats` |
| Admin (`super_admin`/`tenant_admin`/`admin`) | 15 | `/admin/tenants` (GET), `/admin/roles`, `/admin/users` (GET/POST/GET id/PATCH/DELETE), `/admin/logins`, `/admin/conversations` (+ detail), `/admin/audit`, `/admin/stats`, `/admin/schema`, `/admin/feedback`, `/api/rag/reingest` |
| `super_admin` only | 1 + 1 action | `POST /admin/tenants`; hard delete (`DELETE /admin/users/{id}?hard=true`) |

**Tenant isolation** (`routers/admin.py::_tenant_filter`): a non-super admin is pinned to their own tenant for users, logins, conversations, audit, stats and feedback. ✅ Works for reads. Edits have a hole (§6.1).

---

## 5. Layer 3 — Data authorization on every question (VERIFIED)

`auth.authorize(scope, schemes, resolved_entities, sql)` runs three checks in order:

1. **Scheme:** is every scheme in the question in the user's list?
2. **Geography:** for a pinned user, every district/block named in the entities **or** in the SQL (read from the SQLGlot tree, including `UPPER(...)`, every `IN` value and `OR` branches, KI-303) must be in their list. A question with no place at district level or finer is refused, and unparseable SQL is refused (fail closed).
3. **Granularity:** the finest level the query touches (entities, columns, GROUP BY) must not be finer than the role's cap.

A denial returns a polite, specific message, for example *"Your account is authorised for WEST GARO HILLS…"*.

| Where the check runs | Status |
|---|---|
| LangGraph `authorize` node, after `sql_generate`, before `execute_attempt` (`pipeline_graph.py:600-606`) | ✅ |
| MGNREGA fixed query (`mg_det`): its displayed SQL is checked | ✅ |
| Per-scheme / cross-scheme model SQL: all statements are checked together | ✅ |
| PMAY-G fixed queries (`c13:1641`) | ✅ |
| Every **repaired** SQL (up to 3 repairs), KI-183 | ✅ |
| Response cache (exact + semantic) keyed by `scope.cache_fingerprint()`, so a restricted user never receives a wider user's cached answer | ✅ |
| New-chat "which district?" question skipped for pinned officers (scoped by auth instead) | ✅ |
| Every query audited (user, tenant, role, allow/deny, granularity) to `app.query_audit` + JSONL | ✅ |
| Knowledge (RAG) answers: no scope check | ➖ Acceptable: reference docs, not curated data |

---

## 6. Gaps found

### 6.1 HIGH: privilege escalation through `PATCH /admin/users/{id}` (new, KI-418)
`create_user` refuses to let a non-super admin create a `super_admin`, but **`update_user` has no such check** (`routers/admin.py:115-126`). It only checks that the role name exists and that the target user is in the same tenant.

Effects (INFERRED from code, not run):
- A `tenant_admin` or `admin` can PATCH **their own account** to `role: super_admin` and gain cross-tenant power.
- They can **reset the password** of, or deactivate, a `super_admin` in the same tenant. The seeded `superadmin` and `rd-admin` share the default tenant.

**Fix:** in `update_user`, refuse `role == "super_admin"` unless the caller is cross-tenant, and refuse edits to a `super_admin` target by a non-super caller. Add tests.

### 6.2 HIGH/MEDIUM: four answer paths return figures before the data check (new, KI-419)
These run in graph nodes **before** `authorize` (`scope_scheme`, `clarification_gate`, `deterministic`), so a restricted officer gets the figures:

| # | Path | What leaks |
|---|---|---|
| A | `cross_figures.answer` (`c13:1548-1556`, in `clarification_gate`) | Cross-scheme totals and per-district rankings for MGNREGA / PMAY-G / Focus Plus / Focus Legacy |
| B | `_focusplus_overall_summary_answer` (`focus_plus.py:149`, called from `c13:1116`) | Statewide Focus Plus summary (totals, top district, top bank), even for a user without Focus Plus |
| C | `_focus_legacy_pg_name_answer` (`focus_legacy.py:1008-1060`, called from `c13:964`) | One producer group's district, block, members and amount disbursed, from any district |
| D | `_mgnrega_women_unrecorded_answer` (`mgnrega.py:1563`, returned at `c13:1623`) | Women and persons employed for the named place |

A smaller leak: `_mgnrega_admin_expenditure_answer` (`mgnrega.py:1809`) appends a **statewide** figure to a district officer's answer.

**Fix:** call `auth.authorize` (with the shown SQL and resolved entities) before each of these returns, as the PMAY-G path already does. Add one denial test per path.

### 6.3 MEDIUM: `/api/scheme-stats` ignores scope (new, KI-420)
Any logged-in user gets statewide card figures for all six schemes, whatever their scheme list, districts or granularity cap (`routers/stats.py:161`).

### 6.4 MEDIUM: column blind spots (KI-007, already open)
The geography and granularity checks read only `lgd_district` / `lgd_block`. Focus Plus `block_name_raw` and the Assembly Constituency columns (`ac_name`, `assembly_constituency_name`) escape them. For example, `GROUP BY block_name_raw` is treated as state level.

### 6.5 LOW: fail-open and unvalidated per-user fields (new, KI-421)
- `scope_from_user` (`auth.py:177`): if none of a user's `schemes` match a real scheme name (for example a typo such as `PMAY`), the user silently gets **all** schemes.
- `granularity_cap` on a user record **overrides** the role cap, so it can widen access (for example a `state_officer` given `village`). This contradicts the "narrow, never widen" comment. It is also not validated: a bad value such as `"xyz"` would make `GRANULARITY_ORDER.index` raise on the user's next data question.
- A `district_officer` / `block_officer` can be created with no districts. This fails closed (they can see statewide figures only), so it is safe but confusing.

### 6.6 Structural (already tracked)
- **No database-layer backstop:** the app runs as `postgres` (KI-304), there is no row-level security, and privacy tables are protected by `sql_guard` only (KI-004).
- **JWT revocation:** not built (KI-016). Mitigated because the user row is re-read on every request.
- **Plaintext seed passwords** in `app/users.yaml` (KI-023).

### 6.7 Tests
- ✅ `auth.authorize` unit cases: `tests/test_sql_ast.py` (IN lists, UPPER, OR, unparseable SQL) and `tests/test_pipeline_graph.py` (authorize node order; KI-183 repair re-check). District-officer scopes are also used in `test_new_chat_and_scheme_switch_2026_10_21.py` and `test_block_in_other_district_2026_10_19.py`.
- ❌ **No tests** for `require_admin` / `require_super`, tenant isolation, `/admin/users` create/update/delete, or the per-role behaviour of `state_officer` / `block_officer` / `analyst`.
- ❌ No live test that logs in as each role and asks out-of-scope questions.

---

## 7. Scorecard

| Area | Status |
|---|---|
| Role model (8 roles, 3 axes, per-user narrowing) | ✅ Built |
| Login, JWT, password hashing, login audit | ✅ Built |
| Endpoint role gates (user / admin / super) | ✅ Built |
| Tenant isolation on admin reads | ✅ Built |
| Tenant/role safety on admin **writes** | ❌ Escalation hole (6.1) |
| Data checks on model-written SQL + repairs | ✅ Built |
| Data checks on fixed/deterministic answers | ⚠️ 4 of them bypass (6.2) |
| Stats cards scoped by role | ❌ (6.3) |
| All geography columns covered | ⚠️ KI-007 |
| Scope-aware cache | ✅ Built |
| Query audit trail | ✅ Built |
| Admin UI role gating | ✅ Built (cosmetic; server enforces) |
| Database-level enforcement | ❌ Not built (KI-004 / KI-304) |
| Token revocation | ❌ Not built (KI-016, accepted) |
| Tests for admin / role endpoints | ❌ None |

## 8. Recommended order of fixes
1. **6.1:** close the PATCH escalation (small change in `routers/admin.py`, plus tests).
2. **6.2:** add `auth.authorize` to the four early-return paths, plus one denial test each.
3. **6.3:** scope `/api/scheme-stats`, or hide its cards from restricted roles.
4. **6.5:** validate `granularity_cap`, refuse unknown scheme names, require districts for geo-pinned roles.
5. **6.4 / KI-007:** add `block_name_raw` and the AC columns to `infer_granularity` and the geography check.
6. Add an RBAC test file covering each role × each gate, then run a live login-per-role check.
7. Longer term: `megh_readonly` DB role (KI-304) as a second layer.
