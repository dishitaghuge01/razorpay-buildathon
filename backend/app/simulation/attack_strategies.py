"""sybil_flood, collusion_ring, whitewash_return."""

import random
import uuid
from typing import Any

REFUND_DELAY_TICKS = 3

try:
    from app.db import supabase
except Exception:
    from supabase import create_client
    from app.config import SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY

    supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)


def _extract_first_row(response: Any) -> dict:
    if response is None:
        return {}
    data = getattr(response, "data", response)
    if isinstance(data, list):
        return data[0] if data else {}
    if isinstance(data, dict):
        return data
    return {}


def _fetch_account(account_id: str) -> dict:
    response = supabase.table("accounts").select("*").eq("id", account_id).execute()
    return _extract_first_row(response)


def launch_sybil_flood(run_id: str, merchant_id: str, tick: int, ring_size: int = 8) -> dict:
    """Creates `ring_size` accounts (account_type='sybil'), all sharing
    ONE device_fingerprint and ONE ip_subnet (small deliberate variance
    to avoid trivial exact-match detection), kyc_depth=0,
    account_age_days randint(0,3). Each posts a 5-star review with
    transaction_id=None within the SAME tick (timing_correlation signal).
    Inserts one `rings` row (attack_type='sybil_flood') and back-fills
    ground_truth_ring_id on every created account. Returns the rings row."""
    cluster_base = uuid.uuid4().hex[:10]
    shared_prefix = f"10.{random.randint(20, 60)}.{random.randint(10, 60)}"
    ring_row = _extract_first_row(
        supabase.table("rings").insert({
            "run_id": run_id,
            "attack_type": "sybil_flood",
            "launched_tick": tick,
            "member_count": ring_size,
        }).execute()
    )
    ring_id = ring_row["id"]

    account_rows = []
    for index in range(ring_size):
        minor_variation = (index % 5) + 1
        payload = {
            "run_id": run_id,
            "account_label": f"sybil-{uuid.uuid4().hex[:12]}",
            "account_type": "sybil",
            "ground_truth_ring_id": ring_id,
            "device_fingerprint": f"sybil-dev-{cluster_base}-{index:02d}",
            "ip_subnet": f"{shared_prefix}.{minor_variation * 10}/24",
            "payout_account": f"sybil-payout-{uuid.uuid4().hex[:18]}",
            "kyc_depth": 0,
            "account_age_days": random.randint(0, 3),
            "created_tick": tick,
        }
        row = _extract_first_row(supabase.table("accounts").insert(payload).execute())
        account_rows.append(row)
        review_payload = {
            "run_id": run_id,
            "reviewer_account_id": row["id"],
            "merchant_id": merchant_id,
            "transaction_id": None,
            "rating": 5,
            "tick": tick,
        }
        supabase.table("reviews").insert(review_payload).execute()

    return ring_row


def launch_collusion_ring(run_id: str, merchant_id: str, tick: int, ring_size: int = 6) -> dict:
    """Creates `ring_size` accounts (account_type='collusion_ring').
    Each buys from the target merchant, then reviews ANOTHER member's
    prior purchase reciprocally (A reviews B, B reviews C, C reviews A —
    reciprocal_review pattern, don't create the edges row here, that's
    Track B's job in graph_builder.py). After tick + REFUND_DELAY_TICKS (=3),
    engine.py flips a majority of their transactions to
    status='refund_requested' — you do NOT do that flip here, just create
    the accounts/transactions/reviews at creation-tick. Returns the rings row."""
    ring_row = _extract_first_row(
        supabase.table("rings").insert({
            "run_id": run_id,
            "attack_type": "collusion_ring",
            "launched_tick": tick,
            "member_count": ring_size,
        }).execute()
    )
    ring_id = ring_row["id"]

    account_rows = []
    for index in range(ring_size):
        payload = {
            "run_id": run_id,
            "account_label": f"collusion-{uuid.uuid4().hex[:12]}",
            "account_type": "collusion_ring",
            "ground_truth_ring_id": ring_id,
            "device_fingerprint": f"collusion-dev-{uuid.uuid4().hex[:16]}-{index:02d}",
            "ip_subnet": f"10.{random.randint(90, 200)}.{random.randint(1, 200)}.0/24",
            "payout_account": f"collusion-payout-{uuid.uuid4().hex[:20]}",
            "kyc_depth": random.randint(0, 2),
            "account_age_days": random.randint(0, 30),
            "created_tick": tick,
        }
        account_rows.append(_extract_first_row(supabase.table("accounts").insert(payload).execute()))

    transaction_rows = []
    for account in account_rows:
        tx_payload = {
            "run_id": run_id,
            "buyer_account_id": account["id"],
            "merchant_id": merchant_id,
            "amount": round(random.uniform(10.0, 450.0), 2),
            "status": "completed",
            "tick": tick,
            "proof_signature": None,
            "proof_public_key": None,
            "proof_valid": None,
        }
        transaction_rows.append(_extract_first_row(supabase.table("transactions").insert(tx_payload).execute()))

    for index, account in enumerate(account_rows):
        reviewed_account = account_rows[(index + 1) % len(account_rows)]
        reviewed_tx = next(
            tx for tx in transaction_rows if tx["buyer_account_id"] == reviewed_account["id"]
        )
        review_payload = {
            "run_id": run_id,
            "reviewer_account_id": account["id"],
            "merchant_id": merchant_id,
            "transaction_id": reviewed_tx["id"],
            "rating": 5,
            "tick": tick,
        }
        supabase.table("reviews").insert(review_payload).execute()

    return ring_row


def launch_whitewash_return(run_id: str, merchant_id: str, tick: int,
                             burn_account_id: str) -> dict:
    """Marks `burn_account_id` account_type='whitewash'. Spawns ONE new
    account with the SAME device_fingerprint and payout_account as
    burn_account_id but a new account_label and account_age_days=0
    (re-registration). ground_truth_ring_id copies the original ring id
    (used only for scoring, NEVER exposed to the classifier as a feature).
    Returns the rings row."""
    ring_row = _extract_first_row(
        supabase.table("rings").insert({
            "run_id": run_id,
            "attack_type": "whitewash_return",
            "launched_tick": tick,
            "member_count": 2,
        }).execute()
    )
    ring_id = ring_row["id"]

    burn_account = _fetch_account(burn_account_id)
    if burn_account:
        supabase.table("accounts").update({
            "account_type": "whitewash",
            "ground_truth_ring_id": ring_id,
        }).eq("id", burn_account_id).execute()

    if not burn_account:
        raise ValueError(f"Unknown burn_account_id: {burn_account_id}")

    new_account_payload = {
        "run_id": run_id,
        "account_label": f"whitewash-{uuid.uuid4().hex[:12]}",
        "account_type": "whitewash",
        "ground_truth_ring_id": ring_id,
        "device_fingerprint": burn_account["device_fingerprint"],
        "ip_subnet": burn_account["ip_subnet"],
        "payout_account": burn_account["payout_account"],
        "kyc_depth": 0,
        "account_age_days": 0,
        "created_tick": tick,
    }
    _extract_first_row(supabase.table("accounts").insert(new_account_payload).execute())

    return ring_row
