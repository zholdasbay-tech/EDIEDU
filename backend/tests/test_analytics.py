"""Проверяем, что аналитика находит то, что есть, и не выдумывает того, чего нет.
Запуск: pytest -q  (из папки backend)"""
from datetime import date, timedelta

import numpy as np
import pandas as pd

from app import analytics
from app.seed import Profile, generate

TODAY = date(2026, 9, 23)


def rows_from(values: dict, days: int, end: date = TODAY) -> list[dict]:
    out = []
    for i in range(days):
        d = end - timedelta(days=days - 1 - i)
        r = {"date": d.isoformat()}
        for k, v in values.items():
            r[k] = v[i] if isinstance(v, (list, np.ndarray)) else v
        out.append(r)
    return out


def test_finds_planted_sleep_stress_link():
    rng = np.random.default_rng(7)
    rows = generate(Profile(sleep_to_stress=0.7, skip_prob=0.05), TODAY, 60, rng)
    found = analytics.find_patterns(analytics.to_frame(rows))
    pairs = {(p["driver"], p["outcome"]): p for p in found["patterns"]}
    assert ("sleep_hours", "stress") in pairs
    p = pairs[("sleep_hours", "stress")]
    assert p["rho"] < 0                      # больше сна → меньше стресса
    assert p["low_mean"] > p["high_mean"]    # при сне < 7 ч стресс выше


def test_no_patterns_on_pure_noise():
    """На независимом шуме «закономерности» должны находиться редко (поправка BH)."""
    hits = 0
    for seed in range(40):
        rng = np.random.default_rng(1000 + seed)
        n = 60
        rows = rows_from({
            "sleep_hours": rng.choice(np.arange(5, 10.5, 0.5), n),
            "sleep_quality": rng.integers(1, 6, n), "mood": rng.integers(1, 6, n),
            "stress": rng.integers(1, 6, n), "energy": rng.integers(1, 6, n),
            "study_hours": rng.choice(np.arange(0, 6, 0.5), n), "screen_hours": rng.choice(np.arange(0, 7, 0.5), n),
            "activity_min": rng.integers(0, 13, n) * 10,
        }, n)
        if analytics.find_patterns(analytics.to_frame(rows))["patterns"]:
            hits += 1
    assert hits / 40 <= 0.15, f"слишком много ложных находок: {hits} из 40"


def test_too_few_days_gives_nothing():
    rng = np.random.default_rng(3)
    rows = generate(Profile(skip_prob=0), TODAY, 10, rng)
    assert analytics.find_patterns(analytics.to_frame(rows))["patterns"] == []


def test_benjamini_hochberg_known_values():
    q = analytics.benjamini_hochberg([0.01, 0.04, 0.03, 0.20])
    assert np.allclose(q, [0.04, 0.16 / 3, 0.16 / 3, 0.20], atol=1e-6)
    assert analytics.benjamini_hochberg([]) == []


def test_overload_calm_vs_high():
    good = rows_from({"sleep_hours": 9, "mood": 5, "stress": 1, "energy": 5}, 35)
    bad = rows_from({"sleep_hours": [8] * 28 + [5] * 7, "mood": [4] * 28 + [1] * 7,
                     "stress": [2] * 28 + [5] * 7, "energy": [4] * 28 + [1] * 7}, 35)
    g = analytics.overload_index(analytics.to_frame(good))
    b = analytics.overload_index(analytics.to_frame(bad))
    assert g["level"] == "calm" and g["score"] < 10
    assert b["level"] == "high" and b["score"] >= 75
    assert "не хватает сна" in b["reasons"]


def test_overload_needs_four_days():
    rows = rows_from({"sleep_hours": 7, "mood": 3, "stress": 3, "energy": 3}, 3)
    assert analytics.overload_index(analytics.to_frame(rows)) is None


def test_anomaly_on_short_night():
    sleep = [8, 7.5, 8, 8.5, 8] * 6
    sleep[-1] = 4
    rows = rows_from({"sleep_hours": sleep, "mood": 4, "stress": 2, "energy": 4}, 30)
    df = analytics.to_frame(rows)
    an = analytics.find_anomalies(df, pd.Timestamp(TODAY))
    assert any(a["metric"] == "sleep_hours" and not a["good"] for a in an)


def test_care_signal_triggers_and_stays_quiet():
    fine = rows_from({"sleep_hours": 8, "mood": 4, "stress": 2, "energy": 4}, 14)
    rough = rows_from({"sleep_hours": 6, "mood": [4] * 7 + [2, 1, 2, 2, 3, 2, 1], "stress": 3, "energy": 2}, 14)
    df_f, df_r = analytics.to_frame(fine), analytics.to_frame(rough)
    assert analytics.care_signal(df_f, analytics.overload_index(df_f)) is None
    care = analytics.care_signal(df_r, analytics.overload_index(df_r))
    assert care and any(c["phone"] == "150" for c in care["contacts"])


def test_experiment_detects_improvement():
    rng = np.random.default_rng(11)
    start = TODAY - timedelta(days=10)
    rows = generate(Profile(skip_prob=0, experiment=(start, start + timedelta(days=9))), TODAY, 40, rng)
    # усилим эффект, чтобы тест был стабильным
    for r in rows:
        if r["date"] >= start.isoformat():
            r["sleep_quality"] = min(5, r["sleep_quality"] + 1)
    res = analytics.evaluate_experiment(analytics.to_frame(rows), "sleep_quality", start, 10, TODAY)
    assert res["verdict"] == "helped"
    assert res["during_mean"] > res["before_mean"]


def test_streak():
    days = [TODAY - timedelta(days=i) for i in (0, 1, 2, 4)]
    assert analytics.streak(days, TODAY) == 3
    assert analytics.streak(days[1:], TODAY) == 2  # сегодня ещё не отмечено — серия не рвётся


def test_build_insights_empty():
    ins = analytics.build_insights([], TODAY)
    assert ins["summary"]["total_days"] == 0 and ins["overload"] is None
