"""Authentication for the maubot-to-coordinator boundary."""

from hashlib import sha256
from hmac import compare_digest, new


def verify_internal(secret: bytes, body: bytes, signature: str | None) -> bool:
    if not signature or not signature.startswith("sha256="):
        return False
    expected = "sha256=" + new(secret, body, sha256).hexdigest()
    return compare_digest(expected, signature)
