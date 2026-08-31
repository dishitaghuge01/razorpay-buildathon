"""ML-DSA-65 signing via liboqs-python."""

import base64
import ctypes
import json
import os
from typing import Any, Mapping

_LOCAL_LIBS = [
    os.environ.get("OQS_LIB_PATH"),
    os.environ.get("OQS_INSTALL_PATH", "").rstrip("/") + "/lib/liboqs.so" if os.environ.get("OQS_INSTALL_PATH") else None,
    "/home/dishita/_oqs/lib/liboqs.so",
]

for candidate in _LOCAL_LIBS:
    if not candidate:
        continue
    try:
        ctypes.CDLL(candidate)
        break
    except OSError:
        pass

import oqs

ALGORITHM = "ML-DSA-65"  # NIST FIPS 204 standardized name (formerly Dilithium3 pre-standardization)


def canonical_payload(payload: Mapping[str, Any]) -> bytes:
    """Serialize a dict payload deterministically for signature input."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def generate_keypair() -> tuple[str, str]:
    """Generate a stable keypair and return base64-encoded public + secret key bytes."""
    sig = oqs.Signature(ALGORITHM)
    public_key = sig.generate_keypair()
    secret_key = sig.export_secret_key()
    sig.free()
    return base64.b64encode(public_key).decode("ascii"), base64.b64encode(secret_key).decode("ascii")


def _resolve_signature(secret_key: bytes | str | None = None) -> oqs.Signature:
    if secret_key is not None:
        if isinstance(secret_key, str):
            secret_key = base64.b64decode(secret_key)
        try:
            return oqs.Signature(ALGORITHM, secret_key)
        except Exception:
            pass
    sig = oqs.Signature(ALGORITHM)
    sig.generate_keypair()
    return sig


def sign_transaction(payload: Mapping[str, Any], secret_key: bytes | str | None = None) -> str:
    """Sign a canonical JSON payload and return a base64 signature string."""
    sig = _resolve_signature(secret_key)
    try:
        return base64.b64encode(sig.sign(canonical_payload(payload))).decode("ascii")
    finally:
        sig.free()


def verify_transaction(payload: Mapping[str, Any], signature_b64: str, public_key_b64: str) -> bool:
    """Verify the signature for the canonical payload."""
    try:
        signature = base64.b64decode(signature_b64, validate=True)
        public_key = base64.b64decode(public_key_b64, validate=True)
        sig = oqs.Signature(ALGORITHM)
        try:
            return sig.verify(canonical_payload(payload), signature, public_key)
        except Exception:
            return False
        finally:
            sig.free()
    except Exception:
        return False


def forge_tampered_proof(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Create a tampered payload that should fail verification."""
    tampered = dict(payload)
    if "amount" in tampered:
        tampered["amount"] = round(float(tampered["amount"]) + 0.01, 2)
    elif "status" in tampered:
        tampered["status"] = "refund_requested" if tampered.get("status") != "refund_requested" else "completed"
    else:
        tampered["tick"] = int(tampered.get("tick", 0)) + 1
    return tampered

