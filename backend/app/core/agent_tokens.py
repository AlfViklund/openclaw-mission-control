"""Token generation and verification helpers for agent authentication."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID

ITERATIONS = 200_000
SALT_BYTES = 16

_SIGNED_TOKEN_RE = re.compile(r"^agt1\.([0-9a-f-]+)\.(\d+)\.(.+)$")


def generate_agent_token() -> str:
    """Generate a new URL-safe random token for an agent."""
    return secrets.token_urlsafe(32)


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("utf-8").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def hash_agent_token(token: str) -> str:
    """Hash an agent token using PBKDF2-HMAC-SHA256 with a random salt."""
    salt = secrets.token_bytes(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", token.encode("utf-8"), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${_b64encode(salt)}${_b64encode(digest)}"


def verify_agent_token(token: str, stored_hash: str) -> bool:
    """Verify a plaintext token against a stored PBKDF2 hash representation."""
    try:
        algorithm, iterations, salt_b64, digest_b64 = stored_hash.split("$")
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    try:
        iterations_int = int(iterations)
    except ValueError:
        return False
    salt = _b64decode(salt_b64)
    expected_digest = _b64decode(digest_b64)
    candidate = hashlib.pbkdf2_hmac(
        "sha256",
        token.encode("utf-8"),
        salt,
        iterations_int,
    )
    return hmac.compare_digest(candidate, expected_digest)


@dataclass(frozen=True)
class ParsedSignedAgentToken:
    agent_id: UUID
    version: int
    signature: str


def _signing_payload(agent_id: UUID | str, version: int) -> bytes:
    uid = str(agent_id).lower()
    return f"agt1:{uid}:{version}".encode("utf-8")


def issue_signed_agent_token(
    *,
    agent_id: UUID | str,
    version: int,
    secret: str,
) -> str:
    payload = _signing_payload(agent_id, version)
    sig = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()
    sig_b64 = _b64encode(sig)
    uid = str(agent_id).lower()
    return f"agt1.{uid}.{version}.{sig_b64}"


def parse_signed_agent_token(token: str) -> ParsedSignedAgentToken | None:
    from uuid import UUID

    match = _SIGNED_TOKEN_RE.match(token)
    if not match:
        return None
    try:
        agent_id = UUID(match.group(1))
    except (ValueError, AttributeError):
        return None
    try:
        version = int(match.group(2))
    except ValueError:
        return None
    signature = match.group(3)
    return ParsedSignedAgentToken(agent_id=agent_id, version=version, signature=signature)


def verify_signed_agent_token(
    *,
    token: str,
    agent_id: UUID | str,
    version: int,
    secret: str,
) -> bool:
    parsed = parse_signed_agent_token(token)
    if parsed is None:
        return False
    if str(parsed.agent_id).lower() != str(agent_id).lower():
        return False
    if parsed.version != version:
        return False
    expected = issue_signed_agent_token(agent_id=agent_id, version=version, secret=secret)
    return hmac.compare_digest(token, expected)
