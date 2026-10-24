
from app.domain.webhooks.signature import (
    generate_signature,
    verify_signature,
)


def test_valid_signature():
    payload = b'{"event":"user.created"}'
    secret = "test-secret"

    signature = generate_signature(payload, secret)

    assert verify_signature(payload, secret, signature)


def test_tampered_payload_is_rejected():
    secret = "test-secret"
    signature = generate_signature(
        b'{"event":"user.created"}',
        secret,
    )

    assert not verify_signature(
        b'{"event":"user.deleted"}',
        secret,
        signature,
    )


def test_wrong_secret_is_rejected():
    payload = b'{"event":"user.created"}'
    signature = generate_signature(payload, "correct-secret")

    assert not verify_signature(payload, "wrong-secret", signature)


def test_malformed_signature_is_rejected():
    payload = b'{"event":"user.created"}'

    assert not verify_signature(payload, "test-secret", "invalid-signature")
