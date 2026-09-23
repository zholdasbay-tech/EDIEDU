"""Регистрация, вход, сессии.

* Пароли: PBKDF2-HMAC-SHA256, 200 000 итераций, своя соль у каждого пользователя.
  В базе лежит только хеш — даже мы не видим пароль.
* Сессии: случайный токен (secrets, 256 бит). В базе храним не сам токен, а его
  SHA-256 — если базу украдут, войти по ней не получится.
* Защита от перебора: не больше 8 неудачных входов за 15 минут на логин + IP.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

PBKDF2_ITERATIONS = 200_000
SESSION_DAYS = 30


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), PBKDF2_ITERATIONS)
    return digest.hex(), salt


def verify_password(password: str, pw_hash: str, salt: str) -> bool:
    candidate, _ = hash_password(password, salt)
    return hmac.compare_digest(candidate, pw_hash)  # сравнение за постоянное время


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(conn, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)
    conn.execute("INSERT INTO sessions(token_hash, user_id, expires_at) VALUES (?, ?, ?)",
                 (_token_hash(token), user_id, expires.isoformat()))
    return token


def user_by_token(conn, token: str):
    row = conn.execute(
        "SELECT u.*, s.expires_at FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash = ?",
        (_token_hash(token),),
    ).fetchone()
    if not row:
        return None
    if datetime.fromisoformat(row["expires_at"]) < datetime.now(timezone.utc):
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))
        return None
    return row


def drop_session(conn, token: str) -> None:
    conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))


class LoginLimiter:
    """Простой ограничитель в памяти процесса. Для нескольких серверов — Redis."""

    def __init__(self, max_fails: int = 8, window_sec: int = 900):
        self.max_fails = max_fails
        self.window = window_sec
        self.fails: dict[str, deque] = defaultdict(deque)

    def _trim(self, key: str) -> deque:
        q = self.fails[key]
        now = time.monotonic()
        while q and now - q[0] > self.window:
            q.popleft()
        return q

    def blocked(self, key: str) -> bool:
        return len(self._trim(key)) >= self.max_fails

    def fail(self, key: str) -> None:
        self._trim(key).append(time.monotonic())

    def reset(self, key: str) -> None:
        self.fails.pop(key, None)


limiter = LoginLimiter()
