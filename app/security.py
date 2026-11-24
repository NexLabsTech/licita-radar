"""Autenticação local sem cadastro, usando primitivas da biblioteca padrão."""
import base64
import binascii
import getpass
import hashlib
import hmac
import secrets
import sys
import time

ITERATIONS = 600_000
SESSION_SECONDS = 12 * 60 * 60


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_password(password: str, salt: bytes | None = None) -> str:
    if len(password) < 12:
        raise ValueError("Use uma senha de no mínimo 12 caracteres.")
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return "pbkdf2_sha256$" + str(ITERATIONS) + "$" + _b64(salt) + "$" + _b64(digest)


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, rounds, salt, digest = stored.split("$")
        n = int(rounds)
        if algorithm != "pbkdf2_sha256" or n < 300_000 or n > 1_500_000:
            return False
        expected = _decode(digest)
        if len(expected) != 32 or len(_decode(salt)) < 16:
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), _decode(salt), n)
        return hmac.compare_digest(expected, actual)
    except (ValueError, TypeError, OverflowError, UnicodeError, binascii.Error):
        return False


def sign(message: str, secret: str) -> str:
    payload = _b64(message.encode())
    signature = _b64(hmac.new(secret.encode(), payload.encode(), "sha256").digest())
    return payload + "." + signature


def unsign(token: str | None, secret: str) -> str | None:
    if not token or len(token) > 2048:
        return None
    try:
        payload, signature = token.split(".")
        expected = _b64(hmac.new(secret.encode(), payload.encode(), "sha256").digest())
        if not hmac.compare_digest(signature.encode('ascii'), expected.encode('ascii')):
            return None
        return _decode(payload).decode()
    except (ValueError, UnicodeError):
        return None


def make_session(username: str, secret: str, now: int | None = None) -> tuple[str, str]:
    issued = int(time.time()) if now is None else now
    csrf = secrets.token_urlsafe(24)
    return sign(f"{username}|{issued}|{csrf}", secret), csrf


def read_session(token: str | None, username: str, secret: str, now: int | None = None) -> str | None:
    raw = unsign(token, secret)
    if not raw:
        return None
    try:
        user, issued, csrf = raw.split("|")
        current = int(time.time()) if now is None else now
        epoch = int(issued)
        if user != username or not csrf or epoch > current + 60 or current - epoch > SESSION_SECONDS:
            return None
        return csrf
    except ValueError:
        return None


def new_login_csrf(secret: str) -> tuple[str, str]:
    nonce = secrets.token_urlsafe(24)
    return nonce, sign(nonce, secret)


def verify_login_csrf(value: str, signed_cookie: str | None, secret: str) -> bool:
    stored = unsign(signed_cookie, secret)
    return bool(stored and hmac.compare_digest(value, stored))


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "hash-password":
        print(hash_password(getpass.getpass("Nova senha (mín. 12 caracteres): ")))
    else:
        print("Uso: python -m app.security hash-password", file=sys.stderr)
        sys.exit(2)
