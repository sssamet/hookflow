import hashlib
import hmac

SIGNATURE_PREFIX = "sha256="


def generate_signature(payload: bytes, secret: str) -> str:
    digest = hmac.new(
        secret.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()

    return f"{SIGNATURE_PREFIX}{digest}"


def verify_signature(
    payload: bytes,
    secret: str,
    signature: str,
) -> bool:
    if not signature.startswith(SIGNATURE_PREFIX):
        return False

    expected_signature = generate_signature(payload, secret)

    return hmac.compare_digest(expected_signature, signature)