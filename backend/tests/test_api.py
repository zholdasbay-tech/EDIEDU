"""Проверка API целиком: регистрация, отметки, аналитика, права доступа, школа.
Запуск: pytest -q  (из папки backend)"""
import os
import tempfile
from datetime import date, timedelta

os.environ["EDIEDU_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app, today  # noqa: E402

client = TestClient(app)
client.__enter__()  # запускает lifespan: создаёт базу и демо-школу


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def register(username="aliya", password="secret-pass-1"):
    r = client.post("/api/auth/register", json={"username": username, "password": password, "display_name": "Алия"})
    assert r.status_code == 201, r.text
    return r.json()["token"]


def test_health_and_pages():
    assert client.get("/api/health").json()["ok"]
    for page in ("/", "/app", "/school", "/method"):
        r = client.get(page)
        assert r.status_code == 200 and "EdiEdu" in r.text
    assert client.get("/no-such-page").status_code == 404
    assert "Content-Security-Policy" in client.get("/").headers


def test_register_login_and_duplicates():
    register("timur")
    assert client.post("/api/auth/register", json={"username": "timur", "password": "whatever-123"}).status_code == 409
    assert client.post("/api/auth/login", json={"username": "timur", "password": "wrong-pass"}).status_code == 401
    r = client.post("/api/auth/login", json={"username": "timur", "password": "secret-pass-1"})
    assert r.status_code == 200
    me = client.get("/api/me", headers=auth(r.json()["token"])).json()
    assert me["username"] == "timur" and me["role"] == "student"


def test_validation():
    assert client.post("/api/auth/register", json={"username": "a", "password": "short"}).status_code == 422
    t = register("dana")
    bad = client.put(f"/api/checkins/{today().isoformat()}", json={"mood": 7, "stress": 2}, headers=auth(t))
    assert bad.status_code == 422
    future = client.put(f"/api/checkins/{(today() + timedelta(days=1)).isoformat()}", json={"mood": 3, "stress": 2}, headers=auth(t))
    assert future.status_code == 400
    old = client.put(f"/api/checkins/{(today() - timedelta(days=30)).isoformat()}", json={"mood": 3, "stress": 2}, headers=auth(t))
    assert old.status_code == 400
    tag = client.put(f"/api/checkins/{today().isoformat()}", json={"mood": 3, "stress": 2, "tags": ["<script>"]}, headers=auth(t))
    assert tag.status_code == 422


def test_requires_auth():
    assert client.get("/api/insights").status_code == 401
    assert client.get("/api/insights", headers=auth("fake-token")).status_code == 401


def test_checkin_flow_and_insights():
    t = register("arman")
    d = today().isoformat()
    body = {"sleep_hours": 7.5, "sleep_quality": 4, "mood": 4, "stress": 2, "energy": 4,
            "study_hours": 2, "screen_hours": 3, "activity_min": 40, "tags": ["тренировка"], "note": "<b>не html</b>"}
    assert client.put(f"/api/checkins/{d}", json=body, headers=auth(t)).status_code == 200
    rows = client.get("/api/checkins", headers=auth(t)).json()["checkins"]
    assert len(rows) == 1 and rows[0]["note"] == "<b>не html</b>" and rows[0]["tags"] == ["тренировка"]
    # повторное сохранение того же дня — обновление, а не дубликат
    body["mood"] = 5
    client.put(f"/api/checkins/{d}", json=body, headers=auth(t))
    rows = client.get("/api/checkins", headers=auth(t)).json()["checkins"]
    assert len(rows) == 1 and rows[0]["mood"] == 5
    ins = client.get("/api/insights", headers=auth(t)).json()
    assert ins["summary"]["logged_today"] and ins["summary"]["streak"] == 1


def test_student_cannot_open_school_panel():
    t = register("beka")
    assert client.get("/api/school/overview", headers=auth(t)).status_code == 403


def test_demo_student_has_rich_data():
    t = client.post("/api/auth/demo").json()["token"]
    ins = client.get("/api/insights", headers=auth(t)).json()
    assert ins["summary"]["total_days"] > 50
    assert not ins["summary"]["logged_today"]      # сегодня жюри отмечает само
    assert ins["overload"] is not None
    assert len(ins["patterns"]["patterns"]) >= 2
    exps = client.get("/api/experiments", headers=auth(t)).json()["experiments"]
    assert any(x["finished"] for x in exps)
    # демо-аккаунтом нельзя войти по паролю
    me = client.get("/api/me", headers=auth(t)).json()
    assert me["is_demo"] and me["class_name"] == "10Б"


def test_school_panel_is_anonymous():
    t = client.post("/api/auth/demo-school").json()["token"]
    data = client.get("/api/school/overview", headers=auth(t)).json()
    assert len(data["classes"]) == 4
    text = str(data)
    assert "synthetic-" not in text and "demo-" not in text   # никаких логинов
    for c in data["classes"]:
        for w in c["weeks"]:
            if w and not w["hidden"]:
                assert w["n"] >= data["k"]
            if w and w["hidden"]:
                assert "stress" not in w


def test_small_class_is_hidden():
    staff_t = client.post("/api/auth/demo-school").json()["token"]
    # три ученика в новом «классе» — меньше k=5, цифры должны скрыться
    from app.db import get_conn
    with get_conn() as conn:
        sid = conn.execute("SELECT id FROM schools WHERE is_demo = 1").fetchone()["id"]
        conn.execute("INSERT INTO classes(school_id, name, join_code) VALUES (?, 'Мини', 'MINI-1')", (sid,))
    for i in range(3):
        t = register(f"mini{i}")
        client.post("/api/me/join-class", json={"code": "MINI-1"}, headers=auth(t))
        client.put(f"/api/checkins/{today().isoformat()}", json={"mood": 2, "stress": 5, "sleep_hours": 5}, headers=auth(t))
    data = client.get("/api/school/overview", headers=auth(staff_t)).json()
    mini = next(c for c in data["classes"] if c["name"] == "Мини")
    last = mini["weeks"][-1]
    assert last["hidden"] and last["n"] == 3 and "stress" not in last


def test_share_toggle_removes_student_from_school_stats():
    t = register("nursultan")
    client.post("/api/me/join-class", json={"code": "demo-9a"}, headers=auth(t))
    client.patch("/api/me", json={"share_with_school": False}, headers=auth(t))
    assert client.get("/api/me", headers=auth(t)).json()["share_with_school"] is False


def test_experiments_limit_and_export_delete():
    t = register("zhanna")
    for i in range(2):
        assert client.post("/api/experiments", json={"title": f"Опыт {i}", "metric": "mood", "days": 7}, headers=auth(t)).status_code == 201
    assert client.post("/api/experiments", json={"title": "Третий", "metric": "mood"}, headers=auth(t)).status_code == 400
    client.put(f"/api/checkins/{today().isoformat()}", json={"mood": 3, "stress": 3}, headers=auth(t))
    exp = client.get("/api/me/export", headers=auth(t)).json()
    assert len(exp["checkins"]) == 1 and len(exp["experiments"]) == 2
    assert client.delete("/api/me", headers=auth(t)).status_code == 200
    assert client.get("/api/me", headers=auth(t)).status_code == 401   # сессия удалена каскадом
    assert client.post("/api/auth/login", json={"username": "zhanna", "password": "secret-pass-1"}).status_code == 401


def test_login_rate_limit():
    register("ruslan")
    codes = [client.post("/api/auth/login", json={"username": "ruslan", "password": "nope-nope"}).status_code for _ in range(9)]
    assert codes[:8] == [401] * 8 and codes[8] == 429
