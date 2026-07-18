"""Tests for in-process login rate limiting (LoginThrottle + /login wiring)."""

import pytest
from httpx import AsyncClient

from backend.services.rate_limit import LoginThrottle, login_throttle


def test_should_lock_after_threshold():
    t = LoginThrottle(max_failures=3, window_seconds=900, now=lambda: 1000.0)
    for _ in range(3):
        t.record_failure("ip:user")
    with pytest.raises(Exception):  # noqa: B017, PT011 — HTTPException(429)
        t.check("ip:user")


def test_should_clear_failures_on_reset():
    t = LoginThrottle(max_failures=3, window_seconds=900, now=lambda: 1000.0)
    t.record_failure("ip:user")
    t.record_failure("ip:user")
    t.reset("ip:user")
    t.check("ip:user")  # no raise


def test_should_forget_old_failures_after_window_expiry():
    clock = {"t": 1000.0}
    t = LoginThrottle(max_failures=3, window_seconds=10, now=lambda: clock["t"])
    for _ in range(3):
        t.record_failure("k")
    clock["t"] = 1020.0  # past the window
    t.check("k")  # old failures aged out -> no raise


async def test_should_return_429_after_repeated_bad_logins(client: AsyncClient):
    """The (N+1)th failed login from the same client+email is locked out with 429."""
    # Create the admin account so a real user exists (wrong password still fails auth).
    await client.post(
        "/api/auth/setup",
        json={"name": "Admin", "email": "admin@test.com", "password": "adminpass123"},
    )
    bad = {"email": "admin@test.com", "password": "wrong-password"}
    # Isolate this test from any throttle state carried by the module-level singleton.
    login_throttle.reset("testclient:admin@test.com")
    try:
        statuses = []
        for _ in range(6):  # default max_failures=5 -> 6th is locked
            resp = await client.post("/api/auth/login", json=bad)
            statuses.append(resp.status_code)
        assert statuses[-1] == 429
        assert 401 in statuses  # earlier attempts were ordinary auth failures
    finally:
        login_throttle.reset("testclient:admin@test.com")
