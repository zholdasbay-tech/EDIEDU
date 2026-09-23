"""
Аналитика EdiEdu — ядро проекта, написано командой.

Что делает модуль (всё считается по данным ОДНОГО человека, без чужих данных):
  1. personal_baseline   — личная «норма» по каждому показателю (медиана + MAD за 28 дней)
  2. find_anomalies      — насколько сегодняшний день выбивается из нормы (робастный z-score)
  3. find_patterns       — закономерности вида «после короткого сна стресс выше»
                           (корреляция Спирмена + поправка Бенджамини–Хохберга
                            + сравнение групп тестом Манна–Уитни)
  4. overload_index      — индекс перегрузки 0–100 с объяснением, из чего он сложился
  5. weekday_rhythm      — как самочувствие меняется по дням недели
  6. care_signal         — мягкий сигнал «пора поговорить с кем-то» при устойчиво плохом состоянии
  7. evaluate_experiment — итог личного эксперимента «до / во время»

Сторонние библиотеки: pandas (таблицы), numpy (массивы), scipy.stats (статистические тесты).
Сами тесты мы не писали — мы решили, КАКИЕ тесты применять, к каким парам показателей,
с какими порогами, и как переводить результат в понятную фразу.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd
from scipy import stats

# ---------------------------------------------------------------------------
# Описание показателей
# ---------------------------------------------------------------------------

METRICS = {
    "sleep_hours":   {"label": "сон",               "unit": "ч",   "scale": None, "higher_is_better": True},
    "sleep_quality": {"label": "качество сна",      "unit": "/5",  "scale": 5,    "higher_is_better": True},
    "mood":          {"label": "настроение",        "unit": "/5",  "scale": 5,    "higher_is_better": True},
    "stress":        {"label": "стресс",            "unit": "/5",  "scale": 5,    "higher_is_better": False},
    "energy":        {"label": "энергия",           "unit": "/5",  "scale": 5,    "higher_is_better": True},
    "study_hours":   {"label": "учёба после уроков", "unit": "ч",   "scale": None, "higher_is_better": None},
    "screen_hours":  {"label": "экран не для учёбы", "unit": "ч",   "scale": None, "higher_is_better": None},
    "activity_min":  {"label": "движение",          "unit": "мин", "scale": None, "higher_is_better": True},
}

# Подросткам 13–18 лет нужно 8–10 часов сна (рекомендация AASM, 2016).
# Берём нижнюю границу как «достаточно».
SLEEP_NEED_HOURS = 8.0

# Минимум записей, при котором вообще имеет смысл что-то утверждать.
MIN_DAYS_FOR_PATTERNS = 14
MIN_GROUP_SIZE = 4


@dataclass(frozen=True)
class PairSpec:
    """Пара «что может влиять» → «на что», которую мы проверяем.

    lag = 0: оба показателя из одного дня (сон прошлой ночи и стресс сегодня —
             одна запись, потому что сон записывается за ночь ПЕРЕД днём).
    lag = 1: причина сегодня, следствие завтра (экран вечером → сон следующей ночью).
    threshold: граница для деления дней на две группы. None = личная медиана.
    """
    driver: str
    outcome: str
    lag: int
    threshold: Optional[float]
    low_text: str   # продолжение фразы «В дни, когда …» для дней ниже порога
    high_text: str  # продолжение фразы «а когда …» для дней выше порога
    outcome_when: str  # «в тот же день» / «на следующий день»


PAIRS: list[PairSpec] = [
    PairSpec("sleep_hours", "stress", 0, 7.0, "ты спишь меньше 7 часов", "7 часов и больше", "в тот же день"),
    PairSpec("sleep_hours", "mood", 0, 7.0, "ты спишь меньше 7 часов", "7 часов и больше", "в тот же день"),
    PairSpec("sleep_hours", "energy", 0, 7.0, "ты спишь меньше 7 часов", "7 часов и больше", "в тот же день"),
    PairSpec("screen_hours", "sleep_hours", 1, None, "ты проводишь за экраном меньше обычного", "больше обычного", "следующей ночью"),
    PairSpec("screen_hours", "sleep_quality", 1, None, "ты проводишь за экраном меньше обычного", "больше обычного", "следующей ночью"),
    PairSpec("activity_min", "mood", 0, 30.0, "ты двигаешься меньше 30 минут", "30 минут и больше", "в тот же день"),
    PairSpec("activity_min", "sleep_quality", 1, 30.0, "ты двигаешься меньше 30 минут", "30 минут и больше", "следующей ночью"),
    PairSpec("study_hours", "stress", 0, None, "ты занимаешься после уроков меньше обычного", "больше обычного", "в тот же день"),
    PairSpec("study_hours", "sleep_hours", 1, None, "ты занимаешься после уроков меньше обычного", "больше обычного", "следующей ночью"),
]


# ---------------------------------------------------------------------------
# Подготовка данных
# ---------------------------------------------------------------------------

def to_frame(checkins: list[dict]) -> pd.DataFrame:
    """Список записей → таблица с непрерывным календарём (пропущенные дни = NaN).

    Непрерывный календарь важен: сдвиг на 1 день (lag) должен означать
    «следующий календарный день», а не «следующая запись».
    """
    if not checkins:
        return pd.DataFrame(columns=list(METRICS)).astype(float)
    df = pd.DataFrame(checkins)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").set_index("date")
    cols = [c for c in METRICS if c in df.columns]
    df = df[cols].apply(pd.to_numeric, errors="coerce").astype(float)
    full = pd.date_range(df.index.min(), df.index.max(), freq="D")
    return df.reindex(full)


def _fmt(x: float, unit: str = "") -> str:
    """Число по-русски: запятая вместо точки, без лишних нулей."""
    num = f"{x:.0f}" if unit == "мин" else f"{x:.1f}".rstrip("0").rstrip(".")
    num = num.replace(".", ",")
    if unit.startswith("/"):
        return f"{num} из {unit[1:]}"
    return f"{num} {unit}".strip()


# ---------------------------------------------------------------------------
# 1–2. Личная норма и отклонения
# ---------------------------------------------------------------------------

def personal_baseline(df: pd.DataFrame, end: pd.Timestamp, window: int = 28) -> dict:
    """Медиана и MAD за `window` дней ДО `end` (сам день end не входит).

    Медиана и MAD устойчивы к выбросам: одна бессонная ночь не сдвигает «норму».
    """
    past = df.loc[(df.index < end) & (df.index >= end - pd.Timedelta(days=window))]
    out = {}
    for m in METRICS:
        if m not in past:
            continue
        s = past[m].dropna()
        if len(s) < 7:
            continue
        med = float(s.median())
        mad = float((s - med).abs().median())
        out[m] = {"median": med, "mad": mad, "n": int(len(s))}
    return out


def find_anomalies(df: pd.DataFrame, day: pd.Timestamp) -> list[dict]:
    """Робастный z = 0.6745·(x − медиана)/MAD. |z| > 2 считаем заметным отклонением.

    0.6745 делает MAD сопоставимым со стандартным отклонением при нормальном распределении.
    """
    if day not in df.index:
        return []
    base = personal_baseline(df, day)
    row = df.loc[day]
    res = []
    for m in ("sleep_hours", "mood", "stress", "energy", "sleep_quality"):
        if m not in base or pd.isna(row.get(m)):
            continue
        b = base[m]
        # защита от MAD = 0 (человек всегда ставит одно и то же)
        mad = max(b["mad"], 0.5 if METRICS[m]["scale"] else 0.25)
        z = 0.6745 * (row[m] - b["median"]) / mad
        if abs(z) < 2:
            continue
        meta = METRICS[m]
        better = (z > 0) == bool(meta["higher_is_better"])
        direction = "выше" if z > 0 else "ниже"
        res.append({
            "metric": m,
            "value": float(row[m]),
            "usual": b["median"],
            "z": round(float(z), 2),
            "good": better,
            "text": f"{meta['label'].capitalize()} сегодня заметно {direction} твоей нормы: "
                    f"{_fmt(row[m], meta['unit'])} при обычных {_fmt(b['median'], meta['unit'])}.",
        })
    return res


# ---------------------------------------------------------------------------
# 3. Закономерности
# ---------------------------------------------------------------------------

def benjamini_hochberg(pvals: list[float]) -> list[float]:
    """Поправка на множественные сравнения.

    Мы проверяем 9 пар сразу. Если не поправлять, то даже на случайных данных
    примерно каждая двадцатая пара «найдётся» случайно. BH контролирует долю
    ложных находок среди найденных (FDR).
    """
    p = np.asarray(pvals, dtype=float)
    n = len(p)
    if n == 0:
        return []
    order = np.argsort(p)
    ranked = p[order] * n / (np.arange(n) + 1)
    # монотонность: q_i = min_{j>=i} ranked_j
    q_sorted = np.minimum.accumulate(ranked[::-1])[::-1]
    q = np.empty(n)
    q[order] = np.clip(q_sorted, 0, 1)
    return q.tolist()


def find_patterns(df: pd.DataFrame, window_days: int = 90) -> dict:
    """Ищет связи между показателями за последние `window_days` дней.

    Для каждой пары:
      * rho Спирмена (ранговая корреляция — не требует нормальности,
        подходит для шкал 1–5);
      * p-значение → q-значение (BH);
      * дни делятся на две группы по порогу, считаются средние, тест Манна–Уитни.
    Уровни:
      * «pattern» — q < 0.05 и |rho| ≥ 0.3: показываем как закономерность;
      * «hint»    — p < 0.10 и |rho| ≥ 0.25: показываем как «пока намёк».
    """
    if df.empty:
        return {"patterns": [], "hints": [], "tested": 0, "days": 0}
    end = df.index.max()
    d = df.loc[df.index > end - pd.Timedelta(days=window_days)]
    n_days = int(d.dropna(how="all").shape[0])

    candidates = []
    for spec in PAIRS:
        if spec.driver not in d or spec.outcome not in d:
            continue
        x = d[spec.driver]
        y = d[spec.outcome].shift(-spec.lag)  # y(t+lag) напротив x(t)
        pair = pd.concat([x, y], axis=1, keys=["x", "y"]).dropna()
        if len(pair) < MIN_DAYS_FOR_PATTERNS:
            continue
        if pair["x"].nunique() < 3 or pair["y"].nunique() < 2:
            continue
        rho, p = stats.spearmanr(pair["x"], pair["y"])
        if np.isnan(rho):
            continue
        thr = spec.threshold if spec.threshold is not None else float(pair["x"].median())
        low = pair.loc[pair["x"] < thr, "y"]
        high = pair.loc[pair["x"] >= thr, "y"]
        if spec.threshold is None and (len(low) < MIN_GROUP_SIZE or len(high) < MIN_GROUP_SIZE):
            # при медиане и повторяющихся значениях сдвигаем границу на строгое «больше»
            low = pair.loc[pair["x"] <= thr, "y"]
            high = pair.loc[pair["x"] > thr, "y"]
        if len(low) < MIN_GROUP_SIZE or len(high) < MIN_GROUP_SIZE:
            continue
        mw_p = float(stats.mannwhitneyu(low, high, alternative="two-sided").pvalue)
        candidates.append({
            "spec": spec, "rho": float(rho), "p": float(p), "n": int(len(pair)),
            "thr": thr, "low_mean": float(low.mean()), "high_mean": float(high.mean()),
            "n_low": int(len(low)), "n_high": int(len(high)), "mw_p": mw_p,
        })

    qs = benjamini_hochberg([c["p"] for c in candidates])
    patterns, hints = [], []
    for c, q in zip(candidates, qs):
        c["q"] = q
        item = _pattern_to_text(c)
        if q < 0.05 and abs(c["rho"]) >= 0.3:
            item["level"] = "pattern"
            patterns.append(item)
        elif c["p"] < 0.10 and abs(c["rho"]) >= 0.25:
            item["level"] = "hint"
            hints.append(item)
    patterns.sort(key=lambda i: -abs(i["rho"]))
    hints.sort(key=lambda i: -abs(i["rho"]))
    return {"patterns": patterns, "hints": hints, "tested": len(candidates), "days": n_days}


def _strength_word(rho: float) -> str:
    a = abs(rho)
    if a >= 0.6:
        return "сильная"
    if a >= 0.4:
        return "заметная"
    return "умеренная"


def _pattern_to_text(c: dict) -> dict:
    spec: PairSpec = c["spec"]
    om = METRICS[spec.outcome]
    dm = METRICS[spec.driver]
    unit = om["unit"]
    thr_note = ""
    if spec.threshold is None:
        thr_note = f" (твоя обычная граница — {_fmt(c['thr'], dm['unit'])})"
    headline = (
        f"В дни, когда {spec.low_text}, {om['label']} {spec.outcome_when} — в среднем "
        f"{_fmt(c['low_mean'], unit)}, а когда {spec.high_text} — {_fmt(c['high_mean'], unit)}."
    )
    diff = c["high_mean"] - c["low_mean"]
    return {
        "driver": spec.driver,
        "outcome": spec.outcome,
        "lag": spec.lag,
        "rho": round(c["rho"], 2),
        "p": round(c["p"], 4),
        "q": round(c["q"], 4),
        "n": c["n"],
        "n_low": c["n_low"],
        "n_high": c["n_high"],
        "low_mean": round(c["low_mean"], 2),
        "high_mean": round(c["high_mean"], 2),
        "diff": round(diff, 2),
        "threshold": round(c["thr"], 2),
        "strength": _strength_word(c["rho"]),
        "title": f"{dm['label'].capitalize()} → {om['label']}",
        "text": headline + thr_note,
        "fine_print": (
            f"{_strength_word(c['rho']).capitalize()} связь по {c['n']} дням "
            f"(ρ = {format(c['rho'], '.2f').replace('.', ',')}, {'q < 0,001' if c['q'] < 0.001 else 'q = ' + format(c['q'], '.3f').replace('.', ',')}). "
            "Это связь, а не доказанная причина."
        ),
    }


# ---------------------------------------------------------------------------
# 4. Индекс перегрузки
# ---------------------------------------------------------------------------

# Веса выбраны командой по смыслу, а не обучены на данных: у нас нет размеченной
# выборки «выгорел / не выгорел». Поэтому индекс — это сигнал «присмотрись»,
# а не диагноз. Веса вынесены сюда, чтобы их было легко обсуждать и менять.
OVERLOAD_WEIGHTS = {
    "sleep_debt": 0.25,
    "stress_level": 0.25,
    "mood_low": 0.15,
    "energy_low": 0.10,
    "stress_rise": 0.10,
    "trend": 0.15,
}

OVERLOAD_TEXT = {
    "sleep_debt": "не хватает сна",
    "stress_level": "стресс держится высоким",
    "mood_low": "настроение ниже среднего",
    "energy_low": "мало энергии",
    "stress_rise": "стресс выше твоей обычной нормы",
    "trend": "последние две недели становится хуже",
}


def overload_index(df: pd.DataFrame, today: Optional[pd.Timestamp] = None) -> Optional[dict]:
    """Индекс 0–100 по последним 7 дням. Нужно минимум 4 записи из 7."""
    if df.empty:
        return None
    today = today if today is not None else df.index.max()
    week = df.loc[(df.index > today - pd.Timedelta(days=7)) & (df.index <= today)]
    if week["mood"].notna().sum() < 4:
        return None

    def mean(col):
        s = week[col].dropna() if col in week else pd.Series(dtype=float)
        return float(s.mean()) if len(s) else None

    comp = {}
    sleep = mean("sleep_hours")
    comp["sleep_debt"] = 0.0 if sleep is None else float(np.clip((SLEEP_NEED_HOURS - sleep) / 2.5, 0, 1))
    stress = mean("stress")
    comp["stress_level"] = 0.0 if stress is None else float(np.clip((stress - 1) / 4, 0, 1))
    mood = mean("mood")
    comp["mood_low"] = 0.0 if mood is None else float(np.clip((5 - mood) / 4, 0, 1))
    energy = mean("energy")
    comp["energy_low"] = 0.0 if energy is None else float(np.clip((5 - energy) / 4, 0, 1))

    # Рост стресса относительно личной нормы (дни 8–35 назад)
    base = df.loc[(df.index <= today - pd.Timedelta(days=7)) & (df.index > today - pd.Timedelta(days=35)), "stress"].dropna()
    comp["stress_rise"] = 0.0
    if len(base) >= 7 and stress is not None:
        comp["stress_rise"] = float(np.clip((stress - base.mean()) / 1.5, 0, 1))

    # Тренд «напряжения» (стресс минус настроение) за 14 дней: линейная регрессия
    two = df.loc[(df.index > today - pd.Timedelta(days=14)) & (df.index <= today), ["stress", "mood"]].dropna()
    comp["trend"] = 0.0
    trend_info = None
    if len(two) >= 7:
        strain = two["stress"] - two["mood"]
        x = (two.index - two.index.min()).days.to_numpy(dtype=float)
        lr = stats.linregress(x, strain.to_numpy(dtype=float))
        # наклон 0.15 в день ≈ +2 пункта за две недели — это уже много
        if lr.slope > 0 and lr.pvalue < 0.10:
            comp["trend"] = float(np.clip(lr.slope / 0.15, 0, 1))
        trend_info = {"slope_per_day": round(float(lr.slope), 3), "p": round(float(lr.pvalue), 3)}

    contrib = {k: comp[k] * OVERLOAD_WEIGHTS[k] for k in comp}
    score = round(100 * sum(contrib.values()))
    if score < 35:
        level, label = "calm", "Ровно"
        advice = "Сейчас нагрузка в разумных пределах. Хорошее время, чтобы закрепить то, что работает."
    elif score < 60:
        level, label = "watch", "Стоит присмотреться"
        advice = "Нагрузка копится. Не катастрофа, но лучше заранее разгрузить пару вечеров."
    else:
        level, label = "high", "Перегрузка"
        advice = "Похоже, ресурса сейчас мало. Сократи что-то необязательное и поговори с кем-то, кому доверяешь."

    top = sorted(contrib.items(), key=lambda kv: -kv[1])
    reasons = [OVERLOAD_TEXT[k] for k, v in top if v >= 0.04][:3]
    return {
        "score": int(score),
        "level": level,
        "label": label,
        "advice": advice,
        "reasons": reasons,
        "components": {k: round(v, 3) for k, v in comp.items()},
        "weights": OVERLOAD_WEIGHTS,
        "week_means": {"sleep_hours": sleep, "stress": stress, "mood": mood, "energy": energy},
        "trend": trend_info,
        "days_used": int(week["mood"].notna().sum()),
    }


def overload_history(df: pd.DataFrame, days: int = 45) -> list[dict]:
    """Индекс на каждый день — для графика «как менялась нагрузка»."""
    if df.empty:
        return []
    end = df.index.max()
    out = []
    for day in pd.date_range(end - pd.Timedelta(days=days - 1), end, freq="D"):
        if day < df.index.min():
            continue
        oi = overload_index(df.loc[:day], today=day)
        out.append({"date": day.date().isoformat(), "score": None if oi is None else oi["score"]})
    return out


# ---------------------------------------------------------------------------
# 5. Ритм недели
# ---------------------------------------------------------------------------

WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def weekday_rhythm(df: pd.DataFrame, window_days: int = 70) -> Optional[dict]:
    if df.empty:
        return None
    end = df.index.max()
    d = df.loc[df.index > end - pd.Timedelta(days=window_days), ["mood", "stress", "sleep_hours"]].dropna(how="all")
    if len(d) < 14:
        return None
    g = d.groupby(d.index.dayofweek)
    counts = g["mood"].count()
    rows = []
    for i, name in enumerate(WEEKDAYS):
        if i not in counts.index or counts[i] < 2:
            rows.append({"day": name, "mood": None, "stress": None, "sleep_hours": None, "n": int(counts.get(i, 0))})
            continue
        rows.append({
            "day": name,
            "mood": round(float(g["mood"].mean()[i]), 2),
            "stress": round(float(g["stress"].mean()[i]), 2),
            "sleep_hours": round(float(g["sleep_hours"].mean()[i]), 2),
            "n": int(counts[i]),
        })
    valid = [r for r in rows if r["stress"] is not None]
    note = None
    if len(valid) >= 5:
        hardest = max(valid, key=lambda r: r["stress"])
        easiest = min(valid, key=lambda r: r["stress"])
        if hardest["stress"] - easiest["stress"] >= 0.7:
            note = (f"Самый напряжённый день недели — {hardest['day']} "
                    f"(стресс {_fmt(hardest['stress'], '/5')}), самый спокойный — {easiest['day']}.")
    return {"days": rows, "note": note}


# ---------------------------------------------------------------------------
# 6. Сигнал заботы
# ---------------------------------------------------------------------------

def care_signal(df: pd.DataFrame, overload: Optional[dict]) -> Optional[dict]:
    """Не диагноз. Просто правило: если плохо устойчиво, а не один день —
    мягко предлагаем поговорить с живым человеком и даём контакты."""
    if df.empty:
        return None
    end = df.index.max()
    week = df.loc[df.index > end - pd.Timedelta(days=7)]
    low_mood_days = int((week["mood"] <= 2).sum())
    high_stress_days = int((week["stress"] >= 5).sum())
    reasons = []
    if low_mood_days >= 4:
        reasons.append(f"настроение было низким {low_mood_days} дня из последних 7")
    if high_stress_days >= 3:
        reasons.append(f"стресс был на максимуме {high_stress_days} дня из 7")
    if overload and overload["score"] >= 75:
        reasons.append("индекс перегрузки очень высокий")
    if not reasons:
        return None
    return {
        "reasons": reasons,
        "text": "Последняя неделя, похоже, далась тяжело. С таким не нужно справляться в одиночку — "
                "поговори с кем-то, кому доверяешь: другом, родителем, школьным психологом.",
        "contacts": [
            {"name": "Телефон доверия для детей и молодёжи", "phone": "150", "note": "бесплатно, анонимно, на казахском и русском"},
            {"name": "Единый контакт-центр по защите прав детей", "phone": "111", "note": "бесплатно, круглосуточно"},
        ],
    }


# ---------------------------------------------------------------------------
# 7. Личные эксперименты
# ---------------------------------------------------------------------------

def evaluate_experiment(df: pd.DataFrame, metric: str, start: date, days: int, today: date) -> dict:
    """Сравнивает показатель «до» (14 дней перед стартом) и «во время» эксперимента.

    Это эксперимент n = 1 без контрольной группы, поэтому мы честно пишем,
    что результат — подсказка, а не доказательство.
    """
    meta = METRICS[metric]
    start_ts = pd.Timestamp(start)
    end_ts = start_ts + pd.Timedelta(days=days - 1)
    before = df.loc[(df.index < start_ts) & (df.index >= start_ts - pd.Timedelta(days=14)), metric].dropna() if metric in df else pd.Series(dtype=float)
    during = df.loc[(df.index >= start_ts) & (df.index <= end_ts), metric].dropna() if metric in df else pd.Series(dtype=float)
    finished = today > end_ts.date()
    res = {
        "finished": finished,
        "days_logged": int(len(during)),
        "days_total": days,
        "before_mean": round(float(before.mean()), 2) if len(before) else None,
        "during_mean": round(float(during.mean()), 2) if len(during) else None,
        "p": None,
        "verdict": "collecting",
        "text": "Собираем данные. Продолжай отмечать дни.",
    }
    if not finished:
        # Не подглядываем в результат до конца: частые промежуточные проверки
        # повышают шанс случайно «найти» эффект.
        if len(before) and len(during):
            res["text"] = (f"Идёт день {min(days, (today - start).days + 1)} из {days}. Пока: было "
                           f"{_fmt(before.mean(), meta['unit'])}, сейчас {_fmt(during.mean(), meta['unit'])}. "
                           "Вывод сделаем в конце.")
        return res
    if len(before) < 5 or len(during) < 4:
        if finished:
            res["verdict"] = "not_enough"
            res["text"] = "Данных маловато, чтобы делать вывод. Можно повторить эксперимент."
        return res
    p = float(stats.mannwhitneyu(before, during, alternative="two-sided").pvalue)
    diff = float(during.mean() - before.mean())
    res["p"] = round(p, 4)
    res["diff"] = round(diff, 2)
    improved = (diff > 0) == bool(meta["higher_is_better"]) if meta["higher_is_better"] is not None else None
    b, a = _fmt(before.mean(), meta["unit"]), _fmt(during.mean(), meta["unit"])
    if p < 0.05 and improved:
        res["verdict"] = "helped"
        res["text"] = f"Похоже, работает: {meta['label']} было {b}, стало {a}."
    elif p < 0.05 and improved is False:
        res["verdict"] = "worse"
        res["text"] = f"Стало хуже: {meta['label']} было {b}, стало {a}. Может, это не твой способ — и это тоже результат."
    else:
        res["verdict"] = "unclear"
        res["text"] = f"Разница пока не очевидна: было {b}, стало {a}. Возможно, нужно больше дней."
    return res


# ---------------------------------------------------------------------------
# Сборка всего для экрана «Моя картина»
# ---------------------------------------------------------------------------

def streak(dates: list[date], today: date) -> int:
    s = set(dates)
    n = 0
    d = today if today in s else today - timedelta(days=1)
    while d in s:
        n += 1
        d -= timedelta(days=1)
    return n


def build_insights(checkins: list[dict], today: date) -> dict:
    df = to_frame(checkins)
    dates = [date.fromisoformat(c["date"]) if isinstance(c["date"], str) else c["date"] for c in checkins]
    summary = {
        "total_days": len(checkins),
        "streak": streak(dates, today),
        "logged_today": today in set(dates),
        "first_date": min(dates).isoformat() if dates else None,
    }
    if df.empty:
        return {"summary": summary, "overload": None, "overload_history": [], "anomalies": [],
                "patterns": {"patterns": [], "hints": [], "tested": 0, "days": 0},
                "weekday": None, "care": None, "baseline": {}}
    today_ts = pd.Timestamp(today)
    ov = overload_index(df, today=min(today_ts, df.index.max()))
    base = personal_baseline(df, df.index.max() + pd.Timedelta(days=1))
    return {
        "summary": summary,
        "overload": ov,
        "overload_history": overload_history(df),
        "anomalies": find_anomalies(df, today_ts) if today_ts in df.index else [],
        "patterns": find_patterns(df),
        "weekday": weekday_rhythm(df),
        "care": care_signal(df, ov),
        "baseline": {k: {"median": round(v["median"], 2), "n": v["n"]} for k, v in base.items()},
    }
