"""Схемы входных данных (Pydantic). Всё, что приходит от пользователя,
проверяется здесь: типы, диапазоны, длина строк. Невалидный запрос
получает ответ 422 и не доходит до базы."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

ALLOWED_TAGS = {
    "контрольная", "экзамен", "олимпиада", "тренировка", "болею",
    "поссорился", "праздник", "поездка", "дедлайн", "выходной",
}


class RegisterIn(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_.\-]+$")
    password: str = Field(min_length=8, max_length=128)
    display_name: Optional[str] = Field(default=None, max_length=40)


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=128)


class ProfilePatch(BaseModel):
    display_name: Optional[str] = Field(default=None, max_length=40)
    share_with_school: Optional[bool] = None


class JoinClassIn(BaseModel):
    code: str = Field(min_length=4, max_length=12, pattern=r"^[A-Za-z0-9\-]+$")


class CheckinIn(BaseModel):
    sleep_hours: Optional[float] = Field(default=None, ge=0, le=16)
    sleep_quality: Optional[int] = Field(default=None, ge=1, le=5)
    mood: int = Field(ge=1, le=5)
    stress: int = Field(ge=1, le=5)
    energy: Optional[int] = Field(default=None, ge=1, le=5)
    study_hours: Optional[float] = Field(default=None, ge=0, le=16)
    screen_hours: Optional[float] = Field(default=None, ge=0, le=20)
    activity_min: Optional[int] = Field(default=None, ge=0, le=600)
    tags: list[str] = Field(default_factory=list, max_length=6)
    note: str = Field(default="", max_length=280)

    @field_validator("tags")
    @classmethod
    def known_tags(cls, v: list[str]) -> list[str]:
        clean = []
        for t in v:
            t = t.strip().lower()
            if t not in ALLOWED_TAGS:
                raise ValueError(f"неизвестная метка: {t}")
            if t not in clean:
                clean.append(t)
        return clean

    @field_validator("note")
    @classmethod
    def strip_note(cls, v: str) -> str:
        return v.strip()


Metric = Literal["sleep_hours", "sleep_quality", "mood", "stress", "energy"]


class ExperimentIn(BaseModel):
    title: str = Field(min_length=3, max_length=80)
    metric: Metric
    days: int = Field(default=7, ge=5, le=21)
