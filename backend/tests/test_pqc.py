import base64

from app.pqc.signer import ALGORITHM, forge_tampered_proof, generate_keypair, sign_transaction, verify_transaction


def test_keypair_generation():
    pub_b64, secret_b64 = generate_keypair()

    assert ALGORITHM == "ML-DSA-65"
    assert isinstance(pub_b64, str) and len(pub_b64) > 64
    assert isinstance(secret_b64, str) and len(secret_b64) > 64

    # keep the base64 payloads round-trippable and non-empty
    assert base64.b64decode(pub_b64)
    assert base64.b64decode(secret_b64)


def test_sign_verify_roundtrip():
    payload = {
        "run_id": "run-123",
        "buyer_account_id": "acct-1",
        "merchant_id": "m-7",
        "amount": 42.5,
        "status": "completed",
        "tick": 8,
    }

    public_key_b64, secret_key_b64 = generate_keypair()
    signature_b64 = sign_transaction(payload, secret_key=secret_key_b64)

    assert verify_transaction(payload, signature_b64, public_key_b64) is True


def test_sign_verify_tampered_payload_false():
    payload = {
        "run_id": "run-123",
        "buyer_account_id": "acct-2",
        "merchant_id": "m-9",
        "amount": 10.0,
        "status": "completed",
        "tick": 9,
    }

    public_key_b64, secret_key_b64 = generate_keypair()
    signature_b64 = sign_transaction(payload, secret_key=secret_key_b64)
    tampered = dict(payload)
    tampered["amount"] = 99.99

    assert verify_transaction(tampered, signature_b64, public_key_b64) is False


def test_forge_tampered_proof_false():
    payload = {
        "run_id": "run-456",
        "buyer_account_id": "acct-3",
        "merchant_id": "m-11",
        "amount": 14.25,
        "status": "completed",
        "tick": 12,
    }

    public_key_b64, secret_key_b64 = generate_keypair()
    original_sig = sign_transaction(payload, secret_key=secret_key_b64)
    tampered = forge_tampered_proof(payload)

    assert verify_transaction(tampered, original_sig, public_key_b64) is False


def test_malformed_signature_input_false_without_raising():
    payload = {
        "run_id": "run-789",
        "buyer_account_id": "acct-4",
        "merchant_id": "m-13",
        "amount": 5.0,
        "status": "completed",
        "tick": 21,
    }

    public_key_b64, _ = generate_keypair()
    malformed = "this-is-not-valid-base64!!!"

    assert verify_transaction(payload, malformed, public_key_b64) is False
