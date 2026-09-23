"""EdiEdu API (FastAPI).

Запуск:  uvicorn app.main:app --reload   (из папки backend)
Документация API появляется сама: http://127.0.0.1:8000/docs
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import analytics, school
from .auth import create_session, drop_session, hash_password, limiter, user_by_token, verify_password
from .db import get_conn, init_db, transaction
from .schemas import CheckinIn, ExperimentIn, JoinClassIn, LoginIn, ProfilePatch, RegisterIn
from .seed import COLS, create_demo_student, ensure_demo_school

TZ = ZoneInfo(os.environ.get("EDIEDU_TZ", "Asia/Almaty"))
FRONTEND = Path(__file__).resolve().parent.parent.parent / "frontend"
BACKFILL_DAYS = 7  # можно заполнить пропущенный день не старше недели


def today() -> date:
    """«Сегодня» по времени Алматы, а не сервера (сервер может жить в UTC)."""
    return datetime.now(TZ).date()


@asynccontextmanager
async def lifespan(_app):
    init_db()
    with get_conn() as conn, transaction(conn):
        ensure_demo_school(conn, today())
    yield


app = FastAPI(title="EdiEdu API", version="1.0.0", lifespan=lifespan,
              description="Мониторинг самочувствия школьников: отметки, личная аналитика, анонимная панель для школы.")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if not request.url.path.startswith(("/docs", "/openapi", "/redoc")):
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src https://fonts.gstatic.com; img-src 'self' data:; script-src 'self'; "
            "connect-src 'self'; frame-ancestors 'none'"
        )
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


# ---------------------------------------------------------------------------
# Зависимости
# ---------------------------------------------------------------------------

def db():
    with get_conn() as conn:
        yield conn


def current_user(authorization: str = Header(default=""), conn=Depends(db)):
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Нужно войти")
    user = user_by_token(conn, authorization[7:])
    if not user:
        raise HTTPException(401, "Сессия закончилась, войди заново")
    return user


def student(user=Depends(current_user)):
    if user["role"] != "student":
        raise HTTPException(403, "Это раздел для учеников")
    return user


def staff(user=Depends(current_user)):
    if user["role"] != "staff" or not user["school_id"]:
        raise HTTPException(403, "Это раздел для школьного психолога")
    return user


def public_user(u) -> dict:
    return {
        "username": u["username"], "display_name": u["display_name"], "role": u["role"],
        "share_with_school": bool(u["share_with_school"]), "is_demo": bool(u["is_demo"]),
        "class_id": u["class_id"], "school_id": u["school_id"],
    }


# ---------------------------------------------------------------------------
# Аккаунт
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health():
    return {"ok": True, "today": today().isoformat()}


@app.post("/api/auth/register", status_code=201)
def register(body: RegisterIn, conn=Depends(db)):
    if conn.execute("SELECT 1 FROM users WHERE username = ?", (body.username,)).fetchone():
        raise HTTPException(409, "Такой логин уже занят")
    pw_hash, salt = hash_password(body.password)
    uid = conn.execute("INSERT INTO users(username, display_name, pw_hash, pw_salt) VALUES (?, ?, ?, ?)",
                       (body.username, body.display_name, pw_hash, salt)).lastrowid
    return {"token": create_session(conn, uid)}


@app.post("/api/auth/login")
def login(body: LoginIn, request: Request, conn=Depends(db)):
    key = f"{body.username.lower()}|{request.client.host if request.client else '-'}"
    if limiter.blocked(key):
        raise HTTPException(429, "Слишком много попыток. Подожди 15 минут.")
    u = conn.execute("SELECT * FROM users WHERE username = ? AND is_demo = 0", (body.username,)).fetchone()
    if not u or not verify_password(body.password, u["pw_hash"], u["pw_salt"]):
        limiter.fail(key)
        raise HTTPException(401, "Неверный логин или пароль")
    limiter.reset(key)
    return {"token": create_session(conn, u["id"])}


@app.post("/api/auth/demo")
def demo_student(conn=Depends(db)):
    with transaction(conn):
        uid = create_demo_student(conn, today())
    return {"token": create_session(conn, uid)}


@app.post("/api/auth/demo-school")
def demo_school(conn=Depends(db)):
    with transaction(conn):
        ensure_demo_school(conn, today())
    u = conn.execute("SELECT id FROM users WHERE username = 'demo-psychologist'").fetchone()
    return {"token": create_session(conn, u["id"])}


@app.post("/api/auth/logout")
def logout(authorization: str = Header(default=""), conn=Depends(db)):
    if authorization.startswith("Bearer "):
        drop_session(conn, authorization[7:])
    return {"ok": True}


@app.get("/api/me")
def me(user=Depends(current_user), conn=Depends(db)):
    data = public_user(user)
    if user["class_id"]:
        c = conn.execute("SELECT c.name, s.name AS school FROM classes c JOIN schools s ON s.id = c.school_id WHERE c.id = ?",
                         (user["class_id"],)).fetchone()
        data["class_name"], data["school_name"] = c["name"], c["school"]
    elif user["school_id"]:
        data["school_name"] = conn.execute("SELECT name FROM schools WHERE id = ?", (user["school_id"],)).fetchone()["name"]
    return data


@app.patch("/api/me")
def update_me(body: ProfilePatch, user=Depends(current_user), conn=Depends(db)):
    if body.display_name is not None:
        conn.execute("UPDATE users SET display_name = ? WHERE id = ?", (body.display_name.strip() or None, user["id"]))
    if body.share_with_school is not None:
        conn.execute("UPDATE users SET share_with_school = ? WHERE id = ?", (int(body.share_with_school), user["id"]))
    return {"ok": True}


@app.post("/api/me/join-class")
def join_class(body: JoinClassIn, user=Depends(student), conn=Depends(db)):
    c = conn.execute("SELECT id, school_id, name FROM classes WHERE join_code = ? COLLATE NOCASE", (body.code,)).fetchone()
    if not c:
        raise HTTPException(404, "Класс с таким кодом не найден")
    conn.execute("UPDATE users SET class_id = ?, school_id = ? WHERE id = ?", (c["id"], c["school_id"], user["id"]))
    return {"ok": True, "class_name": c["name"]}


@app.post("/api/me/leave-class")
def leave_class(user=Depends(student), conn=Depends(db)):
    conn.execute("UPDATE users SET class_id = NULL, school_id = NULL WHERE id = ?", (user["id"],))
    return {"ok": True}


@app.get("/api/me/export")
def export(user=Depends(current_user), conn=Depends(db)):
    """Право на свои данные: всё, что мы о тебе храним, одним файлом."""
    rows = conn.execute("SELECT * FROM checkins WHERE user_id = ? ORDER BY date", (user["id"],)).fetchall()
    exps = conn.execute("SELECT title, metric, start_date, days FROM experiments WHERE user_id = ?", (user["id"],)).fetchall()
    payload = {
        "exported_at": datetime.now(TZ).isoformat(),
        "profile": public_user(user),
        "checkins": [{k: r[k] for k in r.keys() if k != "user_id"} for r in rows],
        "experiments": [dict(e) for e in exps],
    }
    return JSONResponse(payload, headers={"Content-Disposition": 'attachment; filename="edieedu-export.json"'})


@app.delete("/api/me")
def delete_me(user=Depends(current_user), conn=Depends(db)):
    """Удаление аккаунта — сразу и полностью (каскадом удаляются отметки и сессии)."""
    conn.execute("DELETE FROM users WHERE id = ?", (user["id"],))
    return {"ok": True}


# ---------------------------------------------------------------------------
# Отметки
# ---------------------------------------------------------------------------

def load_checkins(conn, user_id: int, since: date | None = None) -> list[dict]:
    q = f"SELECT {', '.join(COLS)} FROM checkins WHERE user_id = ?"
    args: list = [user_id]
    if since:
        q += " AND date >= ?"
        args.append(since.isoformat())
    return [dict(r) for r in conn.execute(q + " ORDER BY date", args).fetchall()]


@app.get("/api/checkins")
def list_checkins(days: int = 90, user=Depends(student), conn=Depends(db)):
    days = max(7, min(days, 366))
    rows = load_checkins(conn, user["id"], today() - timedelta(days=days - 1))
    for r in rows:
        r["tags"] = [t for t in r["tags"].split(",") if t]
    return {"today": today().isoformat(), "checkins": rows}


@app.put("/api/checkins/{day}")
def upsert_checkin(day: date, body: CheckinIn, user=Depends(student), conn=Depends(db)):
    t = today()
    if day > t:
        raise HTTPException(400, "Нельзя отметить день, который ещё не наступил")
    if day < t - timedelta(days=BACKFILL_DAYS):
        raise HTTPException(400, f"Можно заполнить только последние {BACKFILL_DAYS} дней")
    data = body.model_dump()
    data["tags"] = ",".join(data["tags"])
    data["date"] = day.isoformat()
    conn.execute(
        f"INSERT OR REPLACE INTO checkins(user_id, {', '.join(COLS)}, updated_at) "
        f"VALUES (?, {', '.join('?' * len(COLS))}, datetime('now'))",
        (user["id"], *[data[c] for c in COLS]),
    )
    return {"ok": True}


@app.delete("/api/checkins/{day}")
def delete_checkin(day: date, user=Depends(student), conn=Depends(db)):
    conn.execute("DELETE FROM checkins WHERE user_id = ? AND date = ?", (user["id"], day.isoformat()))
    return {"ok": True}


# ---------------------------------------------------------------------------
# Аналитика и эксперименты
# ---------------------------------------------------------------------------

@app.get("/api/insights")
def insights(user=Depends(student), conn=Depends(db)):
    rows = load_checkins(conn, user["id"], today() - timedelta(days=120))
    return analytics.build_insights(rows, today())


@app.get("/api/experiments")
def list_experiments(user=Depends(student), conn=Depends(db)):
    exps = conn.execute("SELECT * FROM experiments WHERE user_id = ? ORDER BY start_date DESC", (user["id"],)).fetchall()
    if not exps:
        return {"experiments": []}
    df = analytics.to_frame(load_checkins(conn, user["id"], today() - timedelta(days=150)))
    out = []
    for e in exps:
        start = date.fromisoformat(e["start_date"])
        res = analytics.evaluate_experiment(df, e["metric"], start, e["days"], today())
        out.append({"id": e["id"], "title": e["title"], "metric": e["metric"],
                    "metric_label": analytics.METRICS[e["metric"]]["label"],
                    "start_date": e["start_date"], "days": e["days"],
                    "end_date": (start + timedelta(days=e["days"] - 1)).isoformat(), **res})
    return {"experiments": out}


@app.post("/api/experiments", status_code=201)
def start_experiment(body: ExperimentIn, user=Depends(student), conn=Depends(db)):
    active = conn.execute("SELECT COUNT(*) FROM experiments WHERE user_id = ? AND date(start_date, '+' || days || ' days') > ?",
                          (user["id"], today().isoformat())).fetchone()[0]
    if active >= 2:
        raise HTTPException(400, "Одновременно можно вести не больше двух экспериментов — иначе не понять, что сработало")
    eid = conn.execute("INSERT INTO experiments(user_id, title, metric, start_date, days) VALUES (?, ?, ?, ?, ?)",
                       (user["id"], body.title.strip(), body.metric, today().isoformat(), body.days)).lastrowid
    return {"id": eid}


@app.delete("/api/experiments/{exp_id}")
def delete_experiment(exp_id: int, user=Depends(student), conn=Depends(db)):
    conn.execute("DELETE FROM experiments WHERE id = ? AND user_id = ?", (exp_id, user["id"]))
    return {"ok": True}


# ---------------------------------------------------------------------------
# Школа
# ---------------------------------------------------------------------------

@app.get("/api/school/overview")
def school_overview(weeks: int = 8, user=Depends(staff), conn=Depends(db)):
    return school.overview(conn, user["school_id"], today(), max(4, min(weeks, 16)))


# ---------------------------------------------------------------------------
# Сайт (статические файлы)
# ---------------------------------------------------------------------------

@app.exception_handler(404)
async def not_found(request: Request, exc):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": getattr(exc, "detail", "Не найдено")}, status_code=404)
    return FileResponse(FRONTEND / "404.html", status_code=404)


for page in ("app", "school", "method"):
    def _page(p=page):
        return FileResponse(FRONTEND / f"{p}.html")
    app.add_api_route(f"/{page}", _page, include_in_schema=False)

app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="site")
