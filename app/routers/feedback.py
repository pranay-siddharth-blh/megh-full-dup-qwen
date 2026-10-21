"""
👍 / 👎 on chat answers (RAG upgrade Phase 6, 2026-10-15).

  POST /api/feedback    an officer rates an answer: rating 1 / -1 sets (or
                        changes) their vote on that answer, 0 removes it. The
                        question, answer, route, schemes and citations are kept
                        with the vote, so an admin sees what was rated.
  GET  /admin/feedback  admins read the votes, newest first, with totals;
                        tenant_admin sees only their own tenant (as the other
                        /admin routes). ?rating=-1 shows only the 👎.

A 👎 on a knowledge answer is how a wrong or incomplete answer gets found and
turned into a new test question (tests/rag_eval). Everything here is scoped to
the caller: an officer only ever writes their own row.
"""
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app import auth, db
from app.deps import require_admin, require_user

logger = logging.getLogger(__name__)
router = APIRouter(tags=["feedback"])


class Citation(BaseModel):
    title: str = Field(default="", max_length=200)
    section: str = Field(default="", max_length=200)


class FeedbackBody(BaseModel):
    message_key: str = Field(min_length=1, max_length=200)
    rating: int = Field(ge=-1, le=1)              # 1 👍, -1 👎, 0 = take the vote back
    question: str = Field(min_length=1, max_length=2000)
    answer: str = Field(default="", max_length=8000)
    session_id: str | None = Field(default=None, max_length=128)
    route: str | None = Field(default=None, max_length=40)
    schemes: list[str] = Field(default_factory=list, max_length=10)
    citations: list[Citation] = Field(default_factory=list, max_length=5)
    comment: str | None = Field(default=None, max_length=1000)


@router.post("/api/feedback")
async def give_feedback(body: FeedbackBody, scope: auth.UserScope = Depends(require_user)):
    if body.rating == 0:
        await db.execute("DELETE FROM app.answer_feedback WHERE user_id = $1 AND message_key = $2",
                         [scope.db_user_id, body.message_key])
        return {"ok": True, "rating": 0}
    comment = (body.comment or "").strip() or None
    await db.execute(
        """INSERT INTO app.answer_feedback
             (tenant_id, user_id, username, session_id, message_key, question, answer, route,
              schemes, citations, rating, comment)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,$11,$12)
           ON CONFLICT (user_id, message_key) DO UPDATE SET
             rating = EXCLUDED.rating,
             comment = COALESCE(EXCLUDED.comment, app.answer_feedback.comment),
             updated_at = NOW()""",
        [scope.tenant_id, scope.db_user_id, scope.username, body.session_id, body.message_key,
         body.question, body.answer, body.route, [s[:60] for s in body.schemes],
         json.dumps([c.model_dump() for c in body.citations]), body.rating, comment])
    return {"ok": True, "rating": body.rating}


@router.get("/admin/feedback")
async def list_feedback(rating: int | None = Query(None, ge=-1, le=1),
                        limit: int = Query(100, ge=1, le=500),
                        tenant_id: int | None = None,
                        scope: auth.UserScope = Depends(require_admin)):
    tenant = tenant_id if scope.cross_tenant else scope.tenant_id
    where, params = [], []
    if tenant is not None:
        params.append(tenant)
        where.append(f"tenant_id = ${len(params)}")
    totals_where = " AND ".join(where)
    if rating in (1, -1):
        params.append(rating)
        where.append(f"rating = ${len(params)}")
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    params.append(limit)
    rows = await db.fetch_rows(
        f"""SELECT feedback_id, username, session_id, question, answer, route, schemes, citations,
                   rating, comment, created_at, updated_at
            FROM app.answer_feedback {clause}
            ORDER BY updated_at DESC LIMIT ${len(params)}""", params)
    tparams = params[:1] if tenant is not None else []
    totals = await db.fetchrow(
        f"""SELECT count(*) FILTER (WHERE rating = 1) AS up, count(*) FILTER (WHERE rating = -1) AS down
            FROM app.answer_feedback {('WHERE ' + totals_where) if totals_where else ''}""", tparams)
    for r in rows:
        if isinstance(r.get("citations"), str):
            try:
                r["citations"] = json.loads(r["citations"])
            except ValueError:
                r["citations"] = []
    return {"feedback": rows, "up": int((totals or {}).get("up") or 0),
            "down": int((totals or {}).get("down") or 0)}
