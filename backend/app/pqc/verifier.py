"""Signature verification + demo forge helper for ML-DSA-65."""

from app.pqc.signer import ALGORITHM, forge_tampered_proof, verify_transaction

__all__ = ["ALGORITHM", "verify_transaction", "forge_tampered_proof"]
