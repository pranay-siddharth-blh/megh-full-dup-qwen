# Deployment

Target: two application VMs behind the ESDS vFirewall, each running nginx plus
the systemd unit. Capacity budget 20–40 concurrent, 100–200 DAU — see
[../docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md).

The service is a single FastAPI app (`app.main:app`). It talks to Postgres
(`megh_db`) and the self-hosted Qwen gateway on `10.48.242.4`, and Qdrant on `10.48.242.4:6333` (since 2026-10-27, D-074).

---

## 1. Prerequisites on the box

| | |
| --- | --- |
| Python | **3.11+** (verified on 3.11.9) |
| Reachable | `10.48.242.4:5432` (Postgres), `:443` (model gateway); `10.48.242.4:6333` (Qdrant, since 2026-10-27) |
| User | `ubuntu` (matches `User=` in the unit) |

## 2. Lay the code down

```bash
sudo mkdir -p /opt/meghalaya
sudo chown ubuntu:ubuntu /opt/meghalaya
# copy the repo (git clone / rsync / tarball) so it looks like:
#   /opt/meghalaya/app/  data/  web/  deploy/  docs/  requirements.txt
```

The tree must keep its shape: `app/` resolves `data/` and `web/` as siblings
(`Path(__file__).resolve().parents[1]`). Moving `app/` alone will break KB
ingest, the entity resolver, and the static UI routes.

## 3. Virtualenv

```bash
cd /opt/meghalaya
python3.11 -m venv .venv
./.venv/bin/pip install --upgrade pip
./.venv/bin/pip install -r requirements.lock     # reproducible
# or:  ./.venv/bin/pip install -r requirements.txt   (compatible updates)
```

Embeddings come from the gateway's `qwen3-embedding` (`EMBEDDING_PROVIDER=gateway`, D-067). Set
`EMBEDDING_BASE_URL=https://10.48.242.4/openai/v1` (not `…/completions`) and `RAG_MEDIUM_CONFIDENCE=0.35`.
**Since 2026-10-27 (D-074)** Qdrant is `QDRANT_URL=http://10.48.242.4:6333` and the app uses only two
collections, both read-only: `QDRANT_COLLECTION=megh_knowledge` with `QDRANT_KB_READ_ONLY=true` (the app
never builds or rebuilds it) and `SQL_EXAMPLES_COLLECTION=megh_sql_metadata` (`SQL_EXAMPLES_SOURCE=qdrant`, the default; `yaml` = rollback
until the comparison in docs/TESTING.md says otherwise). Also set `RAG_HYBRID_ENABLED=false` (no BM25
vector there) and `CONTEXT_SEMANTIC_MEMORY_ENABLED=false` (see `.env.example`). The memory migration below
applies only to the pre-D-074 setup (D-067) and is not run any more:
`./.venv/bin/python deploy/migrate_conversation_memory.py --dry-run`, then without `--dry-run`.
`fastembed` is still installed: it serves the BM25 keyword vectors, the local re-ranker and the
`EMBEDDING_PROVIDER=local` rollback, and downloads its models on first use — allow outbound HTTPS once, or
pre-seed the `fastembed_cache/`.

## 4. Configuration

```bash
cp .env.example .env
chmod 600 .env          # it holds DB credentials and model API keys
```

Fill in, at minimum:

- `DATABASE_URL` — **use `megh_app`**, not the `postgres` superuser. Create it
  first with [sql/01_create_megh_app_role.sql](sql/01_create_megh_app_role.sql)
  (see *Database roles and retention* below)
- `CHATBOT_DATABASE_URL` — **use `megh_chatbot`** (D-073; the key is exactly this — an unknown key like `DATABASE_URL_CHATBOT` makes settings refuse to load). `CHATBOT_DB_POOL_MAX_SIZE=4`. Startup logs `megh_db chatbot pool ready as 'megh_chatbot'`.
- `READONLY_DATABASE_URL` — **use `megh_readonly`** (the key is `READONLY_DATABASE_URL`, not `DATABASE_URL_READONLY`; set `READONLY_DB_ALLOW_SUPERUSER=False`). Pools: `READONLY_DB_POOL_MAX_SIZE=4`, `DB_POOL_MAX_SIZE=4`, `PIPELINE_GRAPH_PG_POOL_MAX=2` per worker — 2 workers = 20, the ingestion team's limit for all workers together (2026-10-26). Restart the app after the ingestion team announces a database change (the catalog is read at startup).
  ([sql/03_readonly_role.sql](sql/03_readonly_role.sql)). Model-generated SQL
  runs only on this login; a superuser here is refused
- `JWT_SECRET` — long random string; `python -c "import secrets;print(secrets.token_urlsafe(48))"`
- `ADMIN_TOKEN` — same, for the break-glass bootstrap endpoint
- the six model roles (`CLASSIFIER` / `SQL_GENERATION` / `RESPONSE` /
  `EMBEDDING` / `RERANKER` / `ASR` — each `*_BASE_URL` + `*_API_KEY`)
- `QDRANT_URL`, `QDRANT_COLLECTION`

> **`.env` is read by the application, not by systemd.** The unit deliberately
> does not use `EnvironmentFile=`: systemd keeps inline `#` comments as part of
> the value, so `MODEL_MAX_CONCURRENCY=24  # max in-flight` would arrive as the
> string `"24          # max in-flight"` and pydantic would refuse to start.
> pydantic-settings loads `.env` relative to `WorkingDirectory`.

Certificates: if the gateway's self-signed CA must be verified, place the bundle
at `certs/enlight-aiops-internal-ca.pem` and point `AI_MODEL_CA_BUNDLE_PATH` at
it. `certs/` is gitignored — the bundle is environment-specific.

## 5. Service

```bash
sudo cp deploy/systemd/megh-nlpservice.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now megh-nlpservice
sudo systemctl status megh-nlpservice
journalctl -u megh-nlpservice -f
```

## 6. nginx

```bash
sudo cp deploy/nginx/nginx-nlpservice.conf /etc/nginx/sites-available/megh
sudo ln -sf /etc/nginx/sites-available/megh /etc/nginx/sites-enabled/megh
sudo nginx -t && sudo systemctl reload nginx
```

The config carries the OWASP edge hardening (TLS + HSTS, security headers,
per-IP `limit_req`/`limit_conn`, body/timeout caps, dotfile deny, `/admin` +
`/metrics` IP-allowlisting, real-client-IP recovery). Fill in every `# <<SET>>`
placeholder before `nginx -t`:

- `ssl_certificate` / `ssl_certificate_key` — real cert + key (Let's Encrypt via
  the `/.well-known/acme-challenge/` location already stubbed, or an ESDS-issued
  cert). The `limit_req_zone` / `set_real_ip_from` lines at the top must sit in
  an `http{}` context — keep them here if this file is included from `http{}`,
  else move them to `conf.d/`.
- `set_real_ip_from` — the vFirewall / LB subnet. Must match `TRUSTED_PROXIES`
  in `.env` so the app and nginx agree on the client IP.
- `server_name` — the real FQDN once a domain exists.
- the `allow … ; deny all;` CIDRs under `/admin`, `/admin-ui`, `/metrics`.

**Streamed answers (D-039, 2026-10-07):** `nginx-megh-langgraph.conf` has an unbuffered
`location = /api/query/stream` (`proxy_buffering off`, 120 s read timeout; the app pings every 10 s).
Do not add `proxy_set_header` inside that location: it would replace the server-level
`X-Real-IP` / `X-Forwarded-*` headers. The app also sends `X-Accel-Buffering: no`, so the older
`nginx-nlpservice.conf` (left unchanged for the running deploy) streams too.

## 7. WAF — ModSecurity + OWASP CRS

Full runbook: [nginx/modsecurity/README.md](nginx/modsecurity/README.md).
Summary: `apt install libmodsecurity3 libnginx-mod-http-modsecurity`, lay down a
pinned CRS release plus the four config files from `deploy/nginx/modsecurity/`,
uncomment the two `modsecurity …` lines in the site config, reload. It starts in
`SecRuleEngine DetectionOnly` (logs, never blocks) — watch
`/var/log/nginx/modsec_audit.log` on real traffic for a week, add any
false-positive exclusions to `crs-overrides.conf`, then flip to `SecRuleEngine
On` and roll to the second VM. Rollback is one line + reload.

## 8. Verify

```bash
curl -s localhost:8401/health            # anonymous: {"status":"ok"} only
curl -s -H "X-Metrics-Token: $METRICS_TOKEN" localhost:8401/health    # + "components"
curl -s -H "X-Metrics-Token: $METRICS_TOKEN" localhost:8401/metrics   # or an admin JWT
curl -s -H "Authorization: Bearer <user JWT>" localhost:8401/api/rag/status   # KB point count
```

`/health` reports `degraded` with the failing component named when Postgres or
Qdrant is unreachable — the service still starts, by design, so a dependency
outage does not take the whole app down.

Checkpointer: Postgres only (`PIPELINE_GRAPH_CHECKPOINTER_DSN=postgres`, the
default). The first graph request on each worker opens a pool of
`PIPELINE_GRAPH_PG_POOL_MAX` (default 2) connections: 2 VMs x 2 workers x 2 =
8 connections. `/health` -> `components.pipeline_graph` must read `postgres`;
`memory` means the pool could not open (check `DATABASE_URL` / role). The
tables `app.checkpoints`, `app.checkpoint_blobs`, `app.checkpoint_writes`,
`app.checkpoint_migrations` already exist in megh_db (owner `postgres`, v9);
`setup()` is a no-op on them. sql/01 makes `megh_app` the owner of every
`app.*` table, these four included, so `setup()` and `ensure_schema()` keep
working when the app runs as `megh_app`. The `public.checkpoint*` tables belong to another
service; leave them alone. There is no SQLite checkpoint any more; old
`logs/langgraph_checkpoints.sqlite*` files are unused. If Postgres cannot be
opened a worker uses in-process memory and answers stay correct (see
docs/LANGGRAPH_PAUSE_RESUME.md §4).

First start also: creates the `app.*` schema, seeds `app.users` from
`app/users.yaml` **only if that table is empty**, and ingests the scheme KB into
Qdrant (skipped when the collection is already populated).

---

## Side-by-side with an existing deploy (2026-10-04)

An earlier build of this project is already deployed. Nothing in this tree may
overwrite it, so **every name this build uses is different**. Deploy it to its
own directory and the two run in parallel; you switch over only when ready.

| Thing | Existing deploy | This (LangGraph) build |
|---|---|---|
| Directory | `/opt/meghalaya` | **`/opt/meghalaya-langgraph`** |
| systemd unit | `megh-nlpservice.service` | **`megh-langgraph.service`** |
| App port (bare metal) | 8300 | **8410** |
| nginx vhost file | `nginx-nlpservice.conf` | **`nginx-megh-langgraph.conf`** |
| nginx rate-limit zones | `api_rl`, `login_rl`, `conn_per_ip` | **`*_lg`** (must be unique per file) |
| compose project | default (`meghalaya`) | **`megh-langgraph`** (`name:` in compose) |
| Image | `megh-nlp:latest` | **`megh-langgraph:latest`** |
| Containers | `megh-nlp`, `megh-qdrant`, `megh-redis` | **`megh-langgraph-nlp`, `-qdrant`, `-redis`** |
| Container port / host port | 8300 / 8401 | **8400 / 8411** |
| Local Qdrant / Redis host ports | 6333 / 6379 | **6343 / 6389** |
| Named volumes | `meghalaya_hf_cache`, `meghalaya_qdrant_data` | **`megh-langgraph_hf_cache`, `megh-langgraph_qdrant_data`** |

**Why each one matters.** Docker identifies containers, images, networks and
volumes *by name*: re-using a name makes `docker compose up` adopt and replace
the running stack instead of starting a second one. Volume names are prefixed
with the compose project, so `name: megh-langgraph` separates the data too.
systemd keys services by unit filename. Two processes cannot bind one port, and
nginx refuses to start if two enabled vhosts declare the same `limit_req_zone`
name or both claim `default_server`.

### Bare metal

```bash
sudo mkdir -p /opt/meghalaya-langgraph && sudo chown ubuntu:ubuntu /opt/meghalaya-langgraph
# copy THIS tree there (never into /opt/meghalaya), then:
cd /opt/meghalaya-langgraph
python3.11 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
cp /opt/meghalaya/.env .env     # start from the live config, then edit
# .env MUST differ: PORT=8410, and any path/port the old one owns.

sudo cp deploy/systemd/megh-langgraph.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now megh-langgraph
systemctl status megh-langgraph --no-pager      # old service must still be active
curl -s localhost:8410/health                   # new
curl -s localhost:8300/health                   # old, unchanged

sudo cp deploy/nginx/nginx-megh-langgraph.conf /etc/nginx/sites-available/megh-langgraph
# Set a distinct server_name (e.g. chat-new.<domain>) and drop `default_server`
# unless you have removed it from the old vhost.
sudo ln -s /etc/nginx/sites-available/megh-langgraph /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

### Docker

```bash
cd /opt/meghalaya-langgraph
docker compose build && docker compose up -d
docker ps --format '{{.Names}}	{{.Ports}}'    # old megh-nlp must still be listed
curl -s 127.0.0.1:8411/health
```

`docker compose down` here only stops this project, because of the `name:` key.
Run it from `/opt/meghalaya-langgraph`, never from the old directory.

### Switching over / rolling back

Switch: point the DNS name (or the old vhost's `proxy_pass`) at `8410` / `8411`.
Roll back: point it back. Both stacks keep running, so a rollback needs no
rebuild. Retire the old one only after the new build has run cleanly.

## Database roles and retention

Two review-then-run scripts live in [sql/](sql/). Both need a superuser
(`postgres` / `dbadmin`) and are idempotent. Both were validated against the
live database inside a rolled-back transaction.

The service uses two logins, so model-generated SQL never runs with write
access:

| Pool | Setting | Role | Used for |
|---|---|---|---|
| app | `DATABASE_URL` | `megh_app` | the service's own `app.*` writes; trusted, parametrised queries |
| read-only | `READONLY_DATABASE_URL` | `megh_readonly` | catalog reads at startup, the type description of a generated query (parse only), and generated SQL when `CHATBOT_DATABASE_URL` is blank |
| chatbot | `CHATBOT_DATABASE_URL` | `megh_chatbot` | every model-generated query, as `semantic.run_query(sql, 1000, 1000000)` (D-073, 2026-10-27); the login can do nothing else |

**[sql/01_create_megh_app_role.sql](sql/01_create_megh_app_role.sql)** — creates
`megh_app`: SELECT-only on `curated.*` and `semantic.*`, USAGE on `public` (for
`pg_trgm`'s `similarity()`), and **owner** of every `app.*` table (startup's
`ALTER TABLE ... ADD COLUMN IF NOT EXISTS` and the checkpointer's `setup()` need
ownership). No access to `raw` / `staging` / `meta`.

**[sql/03_readonly_role.sql](sql/03_readonly_role.sql)** — hardens
`megh_readonly`: SELECT on every `curated.*` / `semantic.*` object (it was
missing `curated.v_cm_elevate` and `curated.fact_cm_elevate_application`),
nothing else, plus `default_transaction_read_only = on`,
`search_path = curated, semantic` and `statement_timeout = 30s` on the role.
The service also sets the first two on every connection and opens each
generated query with `BEGIN READ ONLY`; the SQLGlot check in `app/sql_guard.py`
rejects any table outside `curated` / `semantic` before it is sent.

Set a real password in each script if the role doesn't exist yet, then:

```bash
psql -d megh_db -f deploy/sql/01_create_megh_app_role.sql
psql -d megh_db -f deploy/sql/03_readonly_role.sql
# then in .env:
#   DATABASE_URL=postgresql://megh_app:<password>@10.48.242.4:5432/megh_db
#   READONLY_DATABASE_URL=postgresql://megh_readonly:<password>@10.48.242.4:5432/megh_db
sudo systemctl restart megh-nlpservice
```

Startup logs `megh_db read-only pool ready as 'megh_readonly'`. If the read-only
login is a superuser the pool is refused (CRITICAL in the log, data questions
fail with a 503) unless `READONLY_DB_ALLOW_SUPERUSER=true`, which is for dev
only. Both scripts were dry-run against the live megh_db inside a rolled-back
transaction on 2026-10-15.

**[sql/02_retention_policy.sql](sql/02_retention_policy.sql)** — adds
`app.purge_expired()`. `app.conversation_turns` holds every question, answer and
generated SQL; `app.query_audit` holds caller IPs. Nothing purges them today.
**The retention windows in that script are placeholders — set them from the
department's policy.** Then schedule it:

```bash
psql -d megh_db -f deploy/sql/02_retention_policy.sql
# crontab (postgres user):
15 3 * * *  psql -d megh_db -c "SELECT * FROM app.purge_expired();" >> /var/log/megh-purge.log 2>&1
```

---

## Before real traffic

- [ ] `DATABASE_URL` uses `megh_app` (sql/01), not the `postgres` superuser
- [ ] `READONLY_DATABASE_URL` uses `megh_readonly` (sql/03); startup logs
      `read-only pool ready as 'megh_readonly'`
- [ ] `JWT_SECRET` and `ADMIN_TOKEN` are real random values, not `CHANGE_ME`
      (startup logs a `CRITICAL` line otherwise — see `docs/SECURITY.md`)
- [ ] the seeded `changeme123` passwords are rotated (`superadmin` first)
- [ ] `ENV=prod` in `.env` (closes `/docs`, `/openapi.json`)
- [ ] TLS terminates in front of the service; `:80` redirects to `:443`
- [ ] `METRICS_TOKEN` set; `/admin` + `/metrics` `allow`/`deny` CIDRs filled in
- [ ] `TRUSTED_PROXIES` (`.env`) and `set_real_ip_from` (nginx) both match the vFirewall/LB subnet
- [ ] `curl -sI https://<host>/` shows the security headers (CSP, HSTS, nosniff, X-Frame-Options)
- [ ] ModSecurity + CRS installed and baked in `DetectionOnly`, then flipped to `On` (section 7)
- [ ] `.env` is `chmod 600` and owned by `ubuntu`
- [ ] retention windows set and `app.purge_expired()` scheduled (sql/02)
- [ ] `python tests/test_security.py` passes against the built venv

## Rollback

The unit is `Restart=always`. To roll back, replace the tree, then:

```bash
sudo systemctl restart megh-nlpservice
```

No migrations need reversing: the schema work is `CREATE TABLE IF NOT EXISTS`
plus `ADD COLUMN IF NOT EXISTS`, so an older build tolerates the newer schema.


## Switching `DATABASE_URL` to `megh_app` (ingestion team, 2026-10-26)
`megh_app` owns the `app` schema and reads `curated` / `semantic` exactly as `megh_readonly`. Checked before the switch
(D-069): no fixed query reads a hidden column or `SELECT *` on a table that hides one; app SQL is `app.`-qualified (the
checkpointer adds `search_path=app` itself); app queries stop at 15 s (megh_app: 60 s). Each worker holds
`DB_POOL_MAX_SIZE` + `PIPELINE_GRAPH_PG_POOL_MAX` = 6 megh_app connections; keep the total across dev + deploy within the
cap agreed with the ingestion team. After switching: restart, `/health`, the full test suite and the live checks.

### Connection caps on megh_db (agreed with the ingestion team, 2026-10-26) — HARD caps
| Login | Per worker | Workers (1 dev + 2 VMs x 2) | Total | Cap |
|---|---|---|---|---|
| `megh_app` (`DATABASE_URL` + checkpointer) | 4 + 2 = 6 | 5 | 30 | 30 |
| `megh_readonly` (generated SQL + catalog reads) | 4 | 5 | 20 | 25 (raised by the team, VERIFIED 2026-10-27) |
| `megh_chatbot` (only `semantic.run_query`; PLANNED for generated SQL, D-072) | — | — | — | 20, its own |

The 31st `megh_app` connection is **refused, not queued**. Tell the ingestion team **before** adding a worker or a VM or
raising any pool. These caps cover only this (LangGraph) build: while the old build (`megh-nlpservice` / Docker `megh-nlp`,
very likely the `172.18.0.2` sessions as `postgres`) runs beside it, its connections come on top. **Stop the old build at
switch-over** so nothing uses `postgres` on megh_db.
