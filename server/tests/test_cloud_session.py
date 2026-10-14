import hashlib
import hmac

import pytest

from airspace.cloud import session
from airspace.cloud.auth import safe_next

SECRET = "k" * 40


def test_sign_has_the_contract_format():
    cookie = session.sign("abc123", SECRET, now=1000)
    user_id, expiry, mac = cookie.split(".")
    assert user_id == "abc123"
    assert int(expiry) == 1000 + session.MAX_AGE == 1000 + 30 * 24 * 3600
    assert mac == hmac.new(SECRET.encode(), f"abc123.{expiry}".encode(), hashlib.sha256).hexdigest()


def test_verify_round_trip():
    cookie = session.sign("abc123", SECRET, now=1000)
    assert session.verify(cookie, SECRET, now=1001) == "abc123"


@pytest.mark.parametrize("tamper", [
    lambda c: c.replace("abc123", "abc124", 1),  # another user
    lambda c: c.rsplit(".", 2)[0] + "." + str(int(c.split(".")[1]) + 999) + "." + c.rsplit(".", 1)[1],  # longer life
    lambda c: c[:-1] + ("0" if c[-1] != "0" else "1"),  # a forged signature
    lambda c: c + ".extra",
    lambda c: c.split(".", 1)[1],
    lambda c: "",
])
def test_verify_rejects_tampering(tamper):
    cookie = session.sign("abc123", SECRET, now=1000)
    assert session.verify(tamper(cookie), SECRET, now=1001) is None


def test_verify_rejects_another_secret():
    cookie = session.sign("abc123", SECRET, now=1000)
    assert session.verify(cookie, "z" * 40, now=1001) is None
    assert session.verify(cookie, "", now=1001) is None


def test_verify_rejects_expired():
    cookie = session.sign("abc123", SECRET, now=1000, max_age=60)
    assert session.verify(cookie, SECRET, now=1059) == "abc123"
    assert session.verify(cookie, SECRET, now=1060) is None


def test_sign_refuses_ids_that_break_the_format():
    with pytest.raises(ValueError):
        session.sign("a.b", SECRET)
    with pytest.raises(ValueError):
        session.sign("abc", "")


@pytest.mark.parametrize("value,expected", [
    (None, "/app"),
    ("", "/app"),
    ("/w/0123456789ab", "/w/0123456789ab"),
    ("/app?tab=keys", "/app?tab=keys"),
    ("//evil.example", "/app"),
    ("/\\evil.example", "/app"),
    ("https://evil.example/app", "/app"),
    ("app", "/app"),
    ("/a\nSet-Cookie: x=1", "/app"),
])
def test_safe_next(value, expected):
    assert safe_next(value) == expected
