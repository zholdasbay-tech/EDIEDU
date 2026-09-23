"""Генератор СИНТЕТИЧЕСКИХ демо-данных.

Важно для честности: это не данные реальных людей. Мы моделируем правдоподобного
школьника и закладываем в модель известные связи (короткий сон → выше стресс,
экран вечером → хуже сон, контрольные → нагрузка). Потом проверяем в тестах,
что наша аналитика эти связи находит, а на случайном шуме — не находит.
На сайте демо-режим всегда подписан как демо.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

import numpy as np

from .auth import hash_password


@dataclass
class Profile:
    base_sleep: float = 7.4          # сколько человек спит «в среднем»
    screen_base: float = 3.0         # часов экрана не для учёбы
    activity_base: float = 35.0      # минут движения
    sleep_to_stress: float = 0.45    # насколько недосып поднимает стресс
    screen_to_sleep: float = 0.35    # сколько сна «съедает» час экрана сверх обычного
    mood_base: float = 3.6
    skip_prob: float = 0.08          # вероятность пропустить отметку
    exam_dates: list = field(default_factory=list)
    experiment: Optional[tuple] = None  # (start, end): вечером без телефона


def _pressure(d: date, exams: list[date]) -> float:
    """Нагрузка перед контрольной: растёт за 7 дней, в день экзамена = 1, после — 0."""
    p = 0.0
    for e in exams:
        delta = (e - d).days
        if 0 <= delta <= 7:
            p = max(p, 1 - delta / 8)
    return p


def generate(profile: Profile, end: date, days: int, rng: np.random.Generator) -> list[dict]:
    out = []
    prev_screen = profile.screen_base
    prev_study = 2.0
    prev_active = False
    for i in range(days):
        d = end - timedelta(days=days - 1 - i)
        weekend = d.weekday() >= 5
        pressure = _pressure(d, profile.exam_dates)
        in_exp = profile.experiment and profile.experiment[0] <= d <= profile.experiment[1]

        # сон прошлой ночи зависит от вчерашнего экрана и учёбы
        sleep = (profile.base_sleep
                 - profile.screen_to_sleep * (prev_screen - profile.screen_base)
                 - 0.25 * (prev_study - 2.0)
                 + (1.1 if weekend else 0)
                 + rng.normal(0, 0.55))
        sleep = float(np.clip(round(sleep * 2) / 2, 3.5, 11))

        screen_mean = profile.screen_base + (1.0 if weekend else 0) - (1.5 if in_exp else 0)
        screen = float(np.clip(round(rng.normal(screen_mean, 1.0) * 2) / 2, 0, 10))
        study = float(np.clip(round(rng.normal(2.0 + 2.6 * pressure - (1.0 if weekend else 0), 0.7) * 2) / 2, 0, 9))
        activity = float(np.clip(round(rng.gamma(2.2, profile.activity_base / 2.2) * (1.4 if weekend else 1) / 5) * 5, 0, 240))
        active = activity >= 30

        stress_c = (2.4 + profile.sleep_to_stress * (7 - sleep) + 0.35 * (study - 2)
                    + 1.3 * pressure + rng.normal(0, 0.55))
        mood_c = (profile.mood_base - 0.45 * (stress_c - 2.4) + (0.35 if active else 0)
                  + (0.25 if weekend else 0) + rng.normal(0, 0.55))
        energy_c = 3.0 + 0.45 * (sleep - 7) + (0.2 if active else 0) - 0.2 * (stress_c - 2.4) + rng.normal(0, 0.5)
        quality_c = (3.1 + 0.45 * (sleep - 7) - 0.3 * (prev_screen - profile.screen_base)
                     + (0.3 if prev_active else 0) + (0.5 if in_exp else 0) + rng.normal(0, 0.6))

        tags = []
        if d in profile.exam_dates:
            tags.append("контрольная")
        elif pressure > 0.6 and rng.random() < 0.3:
            tags.append("дедлайн")
        if activity >= 60:
            tags.append("тренировка")
        if rng.random() < 0.03:
            tags.append("болею")

        prev_screen, prev_study, prev_active = screen, study, active
        if rng.random() < profile.skip_prob:
            continue
        out.append({
            "date": d.isoformat(),
            "sleep_hours": sleep,
            "sleep_quality": int(np.clip(round(quality_c), 1, 5)),
            "mood": int(np.clip(round(mood_c), 1, 5)),
            "stress": int(np.clip(round(stress_c), 1, 5)),
            "energy": int(np.clip(round(energy_c), 1, 5)),
            "study_hours": study,
            "screen_hours": screen,
            "activity_min": int(activity),
            "tags": ",".join(tags),
            "note": "",
        })
    return out


def random_profile(rng: np.random.Generator, exams: list[date]) -> Profile:
    return Profile(
        base_sleep=float(rng.normal(7.3, 0.6)),
        screen_base=float(np.clip(rng.normal(3.0, 1.0), 0.5, 6)),
        activity_base=float(np.clip(rng.normal(35, 15), 5, 90)),
        sleep_to_stress=float(np.clip(rng.normal(0.4, 0.15), 0.05, 0.8)),
        screen_to_sleep=float(np.clip(rng.normal(0.3, 0.12), 0.0, 0.6)),
        mood_base=float(rng.normal(3.6, 0.3)),
        skip_prob=float(np.clip(rng.normal(0.2, 0.1), 0.02, 0.5)),
        exam_dates=exams,
    )


# ---------------------------------------------------------------------------
# Запись в базу
# ---------------------------------------------------------------------------

COLS = ("date", "sleep_hours", "sleep_quality", "mood", "stress", "energy",
        "study_hours", "screen_hours", "activity_min", "tags", "note")


def insert_checkins(conn, user_id: int, rows: list[dict]) -> None:
    conn.executemany(
        f"INSERT OR REPLACE INTO checkins(user_id, {', '.join(COLS)}) VALUES (?, {', '.join('?' * len(COLS))})",
        [(user_id, *[r[c] for c in COLS]) for r in rows],
    )


DEMO_SCHOOL = "Демо-школа (синтетические данные)"
DEMO_CLASSES = ["9А", "10А", "10Б", "11А"]


def ensure_demo_school(conn, today: date) -> int:
    """Создаёт демо-школу с ~95 синтетическими учениками. Если данные устарели
    (последняя запись старше 2 дней) — пересоздаёт, чтобы демо всегда было «свежим»."""
    row = conn.execute("SELECT id FROM schools WHERE is_demo = 1").fetchone()
    if row:
        last = conn.execute(
            """SELECT MAX(k.date) FROM checkins k JOIN users u ON u.id = k.user_id
               WHERE u.school_id = ? AND u.is_demo = 1 AND u.role = 'student'""", (row["id"],)).fetchone()[0]
        if last and date.fromisoformat(last) >= today - timedelta(days=2):
            return row["id"]
        conn.execute("DELETE FROM users WHERE school_id = ? AND is_demo = 1", (row["id"],))
        conn.execute("DELETE FROM schools WHERE id = ?", (row["id"],))

    rng = np.random.default_rng(2026)
    cur = conn.execute("INSERT INTO schools(name, is_demo) VALUES (?, 1)", (DEMO_SCHOOL,))
    school_id = cur.lastrowid
    # у каждого класса свои контрольные — так на панели видно разные «волны»
    exams = {
        "9А":  [today - timedelta(days=33), today - timedelta(days=5)],
        "10А": [today - timedelta(days=40), today - timedelta(days=12)],
        "10Б": [today - timedelta(days=26), today + timedelta(days=1)],
        "11А": [today - timedelta(days=47), today - timedelta(days=19), today - timedelta(days=2)],
    }
    pw_hash, salt = hash_password(secrets.token_urlsafe(16))  # у синтетических учеников вход невозможен
    for name in DEMO_CLASSES:
        code = f"DEMO-{name.replace('А', 'A').replace('Б', 'B')}"
        cid = conn.execute("INSERT INTO classes(school_id, name, join_code) VALUES (?, ?, ?)",
                           (school_id, name, code)).lastrowid
        n = int(rng.integers(21, 27))
        for i in range(n):
            share = 1 if rng.random() < 0.8 else 0
            uid = conn.execute(
                """INSERT INTO users(username, pw_hash, pw_salt, role, school_id, class_id, share_with_school, is_demo)
                   VALUES (?, ?, ?, 'student', ?, ?, ?, 1)""",
                (f"synthetic-{code.lower()}-{i:02d}", pw_hash, salt, school_id, cid, share),
            ).lastrowid
            insert_checkins(conn, uid, generate(random_profile(rng, exams[name]), today, 63, rng))

    conn.execute(
        """INSERT INTO users(username, display_name, pw_hash, pw_salt, role, school_id, is_demo)
           VALUES ('demo-psychologist', 'Школьный психолог (демо)', ?, ?, 'staff', ?, 1)""",
        (pw_hash, salt, school_id),
    )
    return school_id


def create_demo_student(conn, today: date) -> int:
    """Отдельный демо-аккаунт для каждого посетителя: жюри может отмечать дни,
    не мешая друг другу. Данные — до вчерашнего дня, «сегодня» можно отметить самому."""
    school_id = ensure_demo_school(conn, today)
    cls = conn.execute("SELECT id FROM classes WHERE school_id = ? AND name = '10Б'", (school_id,)).fetchone()
    conn.execute("DELETE FROM users WHERE is_demo = 1 AND role = 'student' AND username LIKE 'demo-%' "
                 "AND created_at < datetime('now', '-1 day')")
    pw_hash, salt = hash_password(secrets.token_urlsafe(16))
    uid = conn.execute(
        """INSERT INTO users(username, display_name, pw_hash, pw_salt, role, school_id, class_id, share_with_school, is_demo)
           VALUES (?, 'Алия (демо)', ?, ?, 'student', ?, ?, 1, 1)""",
        (f"demo-{secrets.token_hex(4)}", pw_hash, salt, school_id, cls["id"]),
    ).lastrowid
    rng = np.random.default_rng(3)  # фиксированное зерно: демо одинаковое для всех и воспроизводимо
    exp_start = today - timedelta(days=24)
    profile = Profile(
        base_sleep=7.2, screen_base=3.5, activity_base=32, sleep_to_stress=0.55, screen_to_sleep=0.4,
        skip_prob=0.07,
        exam_dates=[today - timedelta(days=26), today + timedelta(days=1)],
        experiment=(exp_start, exp_start + timedelta(days=9)),
    )
    insert_checkins(conn, uid, generate(profile, today - timedelta(days=1), 70, rng))
    conn.execute("INSERT INTO experiments(user_id, title, metric, start_date, days) VALUES (?, ?, ?, ?, ?)",
                 (uid, "Без телефона за час до сна", "sleep_quality", exp_start.isoformat(), 10))
    conn.execute("INSERT INTO experiments(user_id, title, metric, start_date, days) VALUES (?, ?, ?, ?, ?)",
                 (uid, "20 минут пешком после уроков", "mood", (today - timedelta(days=4)).isoformat(), 7))
    return uid
