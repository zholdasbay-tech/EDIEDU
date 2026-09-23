"""Панель для школьного психолога.

Принцип: психолог видит КЛАССЫ, а не людей.
  * Только ученики, которые сами включили «делиться со школой».
  * Никаких имён, логинов, заметок — в выборку они даже не попадают.
  * k-анонимность: если в группе меньше K учеников, цифры не показываются.
  * Сначала усредняем каждого ученика за неделю, потом класс — чтобы тот,
    кто отмечается каждый день, не «перевешивал» остальных.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

K_ANON = 5


def _week_start(d: pd.Series) -> pd.Series:
    return (d - pd.to_timedelta(d.dt.dayofweek, unit="D")).dt.normalize()


def _fmt(x: float) -> str:
    return f"{x:.1f}".replace(".", ",")


def overview(conn, school_id: int, today: date, weeks: int = 8) -> dict:
    school = conn.execute("SELECT id, name FROM schools WHERE id = ?", (school_id,)).fetchone()
    classes = conn.execute(
        """SELECT c.id, c.name, c.join_code,
                  COUNT(u.id) AS total,
                  COALESCE(SUM(u.share_with_school), 0) AS sharing
           FROM classes c LEFT JOIN users u ON u.class_id = c.id AND u.role = 'student'
           WHERE c.school_id = ? GROUP BY c.id ORDER BY CAST(c.name AS INTEGER), c.name""",
        (school_id,),
    ).fetchall()

    first_week = pd.Timestamp(today) - pd.Timedelta(days=pd.Timestamp(today).dayofweek) - pd.Timedelta(weeks=weeks - 1)
    rows = conn.execute(
        """SELECT u.id AS uid, c.name AS class_name, k.date, k.stress, k.mood, k.sleep_hours, k.tags
           FROM checkins k
           JOIN users u ON u.id = k.user_id
           JOIN classes c ON c.id = u.class_id
           WHERE c.school_id = ? AND u.share_with_school = 1 AND u.role = 'student' AND k.date >= ?""",
        (school_id, first_week.date().isoformat()),
    ).fetchall()

    week_list = [(first_week + pd.Timedelta(weeks=i)).date().isoformat() for i in range(weeks)]
    result = {
        "school": {"id": school["id"], "name": school["name"]} if school else None,
        "k": K_ANON,
        "weeks": week_list,
        "classes": [],
        "school_weeks": [],
        "alerts": [],
        "latest": None,
        "tags": [],
    }
    if not rows:
        for c in classes:
            result["classes"].append({"name": c["name"], "code": c["join_code"], "students_total": c["total"],
                                      "sharing": c["sharing"], "weeks": [None] * weeks})
        return result

    df = pd.DataFrame([dict(r) for r in rows])
    df["date"] = pd.to_datetime(df["date"])
    df["week"] = _week_start(df["date"]).dt.date.astype(str)

    # 1) неделя каждого ученика
    sw = df.groupby(["class_name", "week", "uid"]).agg(
        stress=("stress", "mean"), mood=("mood", "mean"), sleep=("sleep_hours", "mean")).reset_index()
    sw["strain"] = (sw["stress"] >= 3.8) | (sw["sleep"] < 6.5)
    sw["short_sleep"] = sw["sleep"] < 7

    def agg(g: pd.DataFrame) -> dict | None:
        n = int(g["uid"].nunique())
        if n < K_ANON:
            return {"n": n, "hidden": True}
        return {
            "n": n, "hidden": False,
            "stress": round(float(g["stress"].mean()), 2),
            "mood": round(float(g["mood"].mean()), 2),
            "sleep": round(float(g["sleep"].mean()), 2),
            "strain_share": round(float(g["strain"].mean()), 3),
            "short_sleep_share": round(float(g["short_sleep"].mean()), 3),
        }

    # 2) классы по неделям
    for c in classes:
        cw = sw[sw["class_name"] == c["name"]]
        series = []
        for w in week_list:
            g = cw[cw["week"] == w]
            series.append(agg(g) if len(g) else None)
        result["classes"].append({"name": c["name"], "code": c["join_code"], "students_total": c["total"],
                                  "sharing": c["sharing"], "weeks": series})

        # 3) сигналы: последняя неделя с достаточными данными против 4 предыдущих
        valid = [(w, s) for w, s in zip(week_list, series) if s and not s["hidden"]]
        if len(valid) >= 3:
            last_w, last = valid[-1]
            prev = [s for _, s in valid[-5:-1]]
            prev_stress = sum(s["stress"] for s in prev) / len(prev)
            prev_strain = sum(s["strain_share"] for s in prev) / len(prev)
            d_stress = last["stress"] - prev_stress
            d_strain = last["strain_share"] - prev_strain
            if d_stress >= 0.4 or d_strain >= 0.15:
                top_tags = _top_tags(df[(df["class_name"] == c["name"]) & (df["week"] == last_w)])
                hint = ""
                if any(t in ("контрольная", "экзамен", "дедлайн") for t, _ in top_tags[:3]):
                    hint = " Судя по меткам, это период контрольных — хороший момент поговорить о нагрузке и сне."
                result["alerts"].append({
                    "class": c["name"], "week": last_w, "severity": "high" if d_stress >= 0.7 or d_strain >= 0.25 else "medium",
                    "text": f"{c['name']}: средний стресс {_fmt(prev_stress)} → {_fmt(last['stress'])}, "
                            f"перегружены {round(last['strain_share'] * 100)}% учеников "
                            f"(обычно {round(prev_strain * 100)}%).{hint}",
                })

    # 4) вся школа
    for w in week_list:
        g = sw[sw["week"] == w]
        result["school_weeks"].append(agg(g) if len(g) else None)
    valid_school = [(w, s) for w, s in zip(week_list, result["school_weeks"]) if s and not s["hidden"]]
    if valid_school:
        w, s = valid_school[-1]
        result["latest"] = {"week": w, **s}
        result["tags"] = _top_tags(df[df["week"] == w])[:6]
    result["alerts"].sort(key=lambda a: a["severity"] != "high")
    return result


def _top_tags(frame: pd.DataFrame) -> list[tuple[str, int]]:
    """Метки считаем только если их поставили ≥ K разных учеников."""
    counts: dict[str, set] = {}
    for uid, tags in zip(frame["uid"], frame["tags"]):
        for t in filter(None, (tags or "").split(",")):
            counts.setdefault(t, set()).add(uid)
    return sorted(((t, len(u)) for t, u in counts.items() if len(u) >= K_ANON), key=lambda x: -x[1])
