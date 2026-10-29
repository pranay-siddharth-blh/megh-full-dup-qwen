"""Push jira_backlog_v2.json into a Jira Cloud project through the REST API v3 (standard library only).

Credentials come from environment variables, never from this file:
    JIRA_URL        e.g. https://yourcompany.atlassian.net
    JIRA_EMAIL      the Atlassian account email that owns the API token
    JIRA_API_TOKEN  from https://id.atlassian.com/manage-profile/security/api-tokens
    JIRA_PROJECT    project key, e.g. MEGH

Usage:
    python push_to_jira.py --check        # sign in, show project issue types / fields; creates nothing
    python push_to_jira.py --dry-run      # show what would be created
    python push_to_jira.py                # create Epics, then Stories / Tasks under them, then set statuses

Re-runnable: created keys are saved in jira_push_state.json; rows already there are skipped.
"""
import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
BACKLOG = os.path.join(HERE, "jira_backlog_v2.json")
STATE = os.path.join(HERE, "jira_push_state.json")
EXTRA_LABEL = "megh-one-ai"


class Jira:
    def __init__(self, url, email, token):
        self.base = url.rstrip("/")
        cred = base64.b64encode(f"{email}:{token}".encode()).decode()
        self.headers = {"Authorization": "Basic " + cred, "Accept": "application/json",
                        "Content-Type": "application/json"}

    def call(self, method, path, body=None):
        for attempt in range(4):
            try:
                return self._call(method, path, body)
            except (TimeoutError, urllib.error.URLError, ConnectionError) as e:
                if attempt == 3:
                    raise
                print(f"  network error ({e}); retrying")

    def _call(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=self.headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, {"raw": raw.decode(errors="replace")[:500]}


def adf(text, source_id):
    paras = [p for p in text.split(". ") if p]
    return {"type": "doc", "version": 1, "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": text}]},
        {"type": "paragraph", "content": [{"type": "text", "text": f"Backlog id: {source_id}", "marks": [{"type": "em"}]}]},
    ]} if paras else {"type": "doc", "version": 1, "content": []}


def load_state():
    if os.path.exists(STATE):
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state):
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=1)


def discover(j, project):
    st, me = j.call("GET", "/rest/api/3/myself")
    if st != 200:
        sys.exit(f"Sign-in failed ({st}): {me}. Check JIRA_URL, JIRA_EMAIL and JIRA_API_TOKEN.")
    st, proj = j.call("GET", f"/rest/api/3/project/{urllib.parse.quote(project)}")
    if st != 200:
        sys.exit(f"Project {project} not found or not visible ({st}): {proj}")
    st, its = j.call("GET", f"/rest/api/3/issue/createmeta/{urllib.parse.quote(project)}/issuetypes?maxResults=100")
    types = {t["name"].lower(): t for t in (its.get("issueTypes") or its.get("values") or [])}
    fields_by_type = {}
    for name, t in types.items():
        st, fm = j.call("GET", f"/rest/api/3/issue/createmeta/{urllib.parse.quote(project)}/issuetypes/{t['id']}?maxResults=200")
        fields_by_type[name] = {f.get("name", "").lower(): f for f in (fm.get("fields") or fm.get("values") or [])}
    st, comps = j.call("GET", f"/rest/api/3/project/{urllib.parse.quote(project)}/components")
    comp_names = {c["name"].lower(): c["name"] for c in comps} if st == 200 and isinstance(comps, list) else {}
    return {"me": me, "project": proj, "types": types, "fields": fields_by_type, "components": comp_names,
            "style": proj.get("style", "")}


def pick_type(info, wanted):
    t = wanted.lower()
    if t in info["types"]:
        return info["types"][t]["name"], t
    if t == "story" and "task" in info["types"]:
        return info["types"]["task"]["name"], "task"
    sys.exit(f"Issue type {wanted} is not available in this project. Available: {list(info['types'])}")


def field_id(info, tkey, *names):
    fm = info["fields"].get(tkey, {})
    for n in names:
        f = fm.get(n.lower())
        if f:
            return f.get("fieldId") or f.get("key")
    return None


def account_id(j, email, cache):
    if os.environ.get("JIRA_ASSIGNEE_ACCOUNT"):  # explicit account id wins (emails are often hidden)
        return os.environ["JIRA_ASSIGNEE_ACCOUNT"]
    if email in cache:
        return cache[email]
    st, users = j.call("GET", "/rest/api/3/user/search?query=" + urllib.parse.quote(email))
    cache[email] = users[0]["accountId"] if st == 200 and users else None
    return cache[email]


def build_fields(j, info, row, project, parent_key, ucache):
    tname, tkey = pick_type(info, row["Issue Type"])
    labels = [l.strip().replace(" ", "-") for l in row["Labels"].split(";") if l.strip()] + [EXTRA_LABEL]
    f = {"project": {"key": project}, "issuetype": {"name": tname}, "summary": row["Summary"][:254],
         "description": adf(row["Description"], row["Issue ID"]), "labels": labels}
    fm = info["fields"].get(tkey, {})
    if "priority" in fm and row["Priority"]:
        f["priority"] = {"name": row["Priority"]}
    comps = [info["components"][c.strip().lower()] for c in row["Components"].split(";")
             if c.strip().lower() in info["components"]]
    if comps and "components" in fm:
        f["components"] = [{"name": c} for c in comps]
    sp = field_id(info, tkey, "Story Points", "Story point estimate")
    if sp and row["Story Points"]:
        f[sp] = float(row["Story Points"])
    if "assignee" in fm and row.get("Assignee"):
        aid = account_id(j, row["Assignee"], ucache)
        if aid:
            f["assignee"] = {"accountId": aid}
    if tkey == "epic":
        en = field_id(info, tkey, "Epic Name")
        if en:
            f[en] = row["Summary"][:60]
    if parent_key:
        if "parent" in fm or info["style"] == "next-gen":
            f["parent"] = {"key": parent_key}
        else:
            el = field_id(info, tkey, "Epic Link")
            f[el or "parent"] = parent_key if el else {"key": parent_key}
    return f


def create(j, fields):
    st, res = j.call("POST", "/rest/api/3/issue", {"fields": fields})
    if st == 201:
        return res["key"], None
    errs = (res.get("errors") or {}) if isinstance(res, dict) else {}
    droppable = [k for k in errs if k in fields and k not in ("project", "issuetype", "summary")]
    if droppable:  # retry once without the optional fields Jira rejected
        for k in droppable:
            fields.pop(k, None)
        st, res = j.call("POST", "/rest/api/3/issue", {"fields": fields})
        if st == 201:
            return res["key"], f"dropped {droppable}"
    return None, f"{st} {res}"


def transition(j, key, status):
    if not status or status.lower() == "to do":
        return "kept initial status"
    st, tr = j.call("GET", f"/rest/api/3/issue/{key}/transitions")
    want = status.lower()
    for t in tr.get("transitions", []):
        if t["to"]["name"].lower() == want or t["name"].lower() == want:
            st, _ = j.call("POST", f"/rest/api/3/issue/{key}/transitions", {"transition": {"id": t["id"]}})
            return f"-> {t['to']['name']}" if st == 204 else f"transition failed {st}"
    if want == "done":  # some workflows need In Progress first
        for t in tr.get("transitions", []):
            if "progress" in t["to"]["name"].lower():
                j.call("POST", f"/rest/api/3/issue/{key}/transitions", {"transition": {"id": t["id"]}})
                return transition(j, key, status)
    return f"no transition to {status} (have {[t['to']['name'] for t in tr.get('transitions', [])]})"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", help="comma-separated backlog ids, e.g. E3,E3-01")
    a = ap.parse_args()

    env = {k: os.environ.get(k, "").strip() for k in ("JIRA_URL", "JIRA_EMAIL", "JIRA_API_TOKEN", "JIRA_PROJECT")}
    missing = [k for k, v in env.items() if not v]
    if missing:
        sys.exit("Set these environment variables first: " + ", ".join(missing))
    with open(BACKLOG, encoding="utf-8") as f:
        rows = json.load(f)
    if a.only:
        keep = set(a.only.split(","))
        rows = [r for r in rows if r["Issue ID"] in keep]

    j = Jira(env["JIRA_URL"], env["JIRA_EMAIL"], env["JIRA_API_TOKEN"])
    info = discover(j, env["JIRA_PROJECT"])
    print(f"Signed in as {info['me'].get('displayName')} | project {info['project']['key']} "
          f"({info['project']['name']}, style={info['style'] or 'classic'})")
    print("Issue types:", ", ".join(t["name"] for t in info["types"].values()))
    print("Components in project:", ", ".join(info["components"].values()) or "none (component column skipped)")
    if a.check:
        for t in ("epic", "story", "task"):
            print(f"  {t}: fields =", sorted(info["fields"].get(t, {}))[:40])
        return

    state = load_state()
    ucache = {}
    epics = [r for r in rows if r["Issue Type"] == "Epic"]
    children = [r for r in rows if r["Issue Type"] != "Epic"]
    made, failed = 0, 0
    for r in epics + children:
        rid = r["Issue ID"]
        if rid in state:
            print(f"skip {rid} (already {state[rid]})")
            continue
        parent_key = state.get(r["Parent ID"]) if r["Parent ID"] else None
        if r["Parent ID"] and not parent_key and not a.dry_run:
            print(f"FAIL {rid}: parent {r['Parent ID']} was not created")
            failed += 1
            continue
        fields = build_fields(j, info, r, env["JIRA_PROJECT"], parent_key or ("<" + r["Parent ID"] + ">" if r["Parent ID"] else None), ucache)
        if a.dry_run:
            print(f"would create {fields['issuetype']['name']:6} {rid:6} parent={r['Parent ID'] or '-':3} "
                  f"status={r['Status']:11} {r['Summary'][:70]}")
            continue
        key, note = create(j, fields)
        if not key:
            print(f"FAIL {rid}: {note}")
            failed += 1
            continue
        state[rid] = key
        save_state(state)
        made += 1
        print(f"created {key} <- {rid} {note or ''} {transition(j, key, r['Status'])}")
    if not a.dry_run:
        print(f"Done: {made} created, {failed} failed, {len(state)} in {os.path.basename(STATE)}. "
              f"Board: {env['JIRA_URL'].rstrip('/')}/jira/software/projects/{env['JIRA_PROJECT']}/issues")


if __name__ == "__main__":
    main()
