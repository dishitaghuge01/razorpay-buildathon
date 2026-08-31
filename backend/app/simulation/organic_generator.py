"""Organic account/transaction/review generation."""

import random
import uuid
from functools import lru_cache
from typing import Any

try:
    from app.db import supabase
except Exception:
    from supabase import create_client
    from app.config import SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY

    supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)


@lru_cache(maxsize=1)
def _organic_keypair() -> tuple[str, str]:
    from app.pqc.signer import generate_keypair

    return generate_keypair()


def _extract_first_row(response: Any) -> dict:
    if response is None:
        return {}
    data = getattr(response, "data", response)
    if isinstance(data, list):
        return data[0] if data else {}
    if isinstance(data, dict):
        return data
    return {}


def _get_random_merchant_id(run_id: str) -> str | None:
    response = supabase.table("merchants").select("id").eq("run_id", run_id).execute()
    merchants = getattr(response, "data", response)
    if not merchants:
        return None
    return random.choice(merchants)["id"]


def _get_random_organic_account_id(run_id: str) -> str | None:
    response = supabase.table("accounts").select("id").eq("run_id", run_id).eq("account_type", "organic").execute()
    accounts = getattr(response, "data", response)
    if not accounts:
        return None
    return random.choice(accounts)["id"]


def generate_organic_account(run_id: str, tick: int) -> dict:
    """Returns the dict matching the `accounts` table columns exactly
    (account_type='organic', ground_truth_ring_id=None,
    unique device_fingerprint/ip_subnet/payout_account per account,
    kyc_depth randint(1,3), account_age_days randint(30,900)).
    Inserts the row via supabase client and returns the inserted row."""
    payload = {
        "run_id": run_id,
        "account_label": f"organic-{uuid.uuid4().hex[:12]}",
        "account_type": "organic",
        "ground_truth_ring_id": None,
        "device_fingerprint": f"org-dev-{uuid.uuid4().hex}",
        "ip_subnet": f"10.{random.randint(10, 210)}.{random.randint(1, 254)}.0/24",
        "payout_account": f"payout_{uuid.uuid4().hex[:20]}",
        "kyc_depth": random.randint(1, 3),
        "account_age_days": random.randint(30, 900),
        "created_tick": tick,
    }
    response = supabase.table("accounts").insert(payload).execute()
    return _extract_first_row(response)


def generate_organic_transaction(run_id: str, account_id: str, merchant_id: str, tick: int) -> dict:
    """amount ~ lognormal, status='completed'. Calls
    pqc.signer.sign_transaction() before insert, populates
    proof_signature, proof_public_key, proof_valid=True."""
    amount = max(1.0, float(random.lognormvariate(2.3, 0.9)))
    payload = {
        "run_id": run_id,
        "buyer_account_id": account_id,
        "merchant_id": merchant_id,
        "amount": round(amount, 2),
        "status": "completed",
        "tick": tick,
        "proof_signature": None,
        "proof_public_key": None,
        "proof_valid": None,
    }

    try:
        from app.pqc.signer import sign_transaction  # type: ignore

        public_key_b64, secret_key_b64 = _organic_keypair()
        signature = sign_transaction(payload, secret_key=secret_key_b64)
        payload["proof_signature"] = signature
        payload["proof_public_key"] = public_key_b64
        payload["proof_valid"] = True
    except Exception:
        payload["proof_signature"] = None
        payload["proof_public_key"] = None
        payload["proof_valid"] = None

    response = supabase.table("transactions").insert(payload).execute()
    return _extract_first_row(response)


def generate_organic_review(run_id: str, account_id: str, merchant_id: str,
                             transaction_id: str | None, tick: int) -> dict:
    """rating skewed toward 4-5 with normal variance (organic behavior)."""
    if random.random() < 0.75:
        rating = int(round(random.gauss(4.6, 0.5)))
    else:
        rating = int(round(random.gauss(3.7, 0.9)))
    rating = max(1, min(5, rating))
    payload = {
        "run_id": run_id,
        "reviewer_account_id": account_id,
        "merchant_id": merchant_id,
        "transaction_id": transaction_id,
        "rating": rating,
        "tick": tick,
    }
    response = supabase.table("reviews").insert(payload).execute()
    return _extract_first_row(response)


def run_organic_tick(run_id: str, tick: int,
                      new_accounts_per_tick: int = 3,
                      tx_per_tick: int = 5) -> None:
    """Orchestrates the three functions above for one tick.
    This is the ONLY function called by simulation/engine.py for organic traffic."""
    for _ in range(new_accounts_per_tick):
        generate_organic_account(run_id, tick)

    merchant_ids = supabase.table("merchants").select("id").eq("run_id", run_id).execute()
    merchant_list = getattr(merchant_ids, "data", merchant_ids)
    if not merchant_list:
        return

    account_ids = supabase.table("accounts").select("id").eq("run_id", run_id).eq("account_type", "organic").execute()
    account_list = getattr(account_ids, "data", account_ids)
    if not account_list:
        return

    for _ in range(tx_per_tick):
        merchant_id = random.choice(merchant_list)["id"]
        account_id = random.choice(account_list)["id"]
        tx_row = generate_organic_transaction(run_id, account_id, merchant_id, tick)
        generate_organic_review(run_id, account_id, merchant_id, tx_row.get("id"), tick)
