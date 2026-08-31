"""Feature vector extraction for ML."""

from __future__ import annotations

import math

import numpy as np

from app.db import supabase

VELOCITY_WINDOW_TICKS = 5
FEATURE_ORDER = [
    "reciprocity_score",
    "collateral_score",
    "proof_validity_ratio_inv",
    "velocity_score",
    "device_overlap_max",
    "avg_account_age_inv",
    "review_to_purchase_ratio",
]


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _load_accounts(member_account_ids: list[str], run_id: str) -> list[dict]:
    if not member_account_ids:
        return []
    response = supabase.table("accounts").select("id, kyc_depth, account_age_days").eq("run_id", run_id).in_("id", member_account_ids).execute()
    return getattr(response, "data", response) or []


def compute_reciprocity_score(member_account_ids: list[str], run_id: str) -> float:
    """Fraction of reciprocal_review edges present among all possible
    pairs within the cluster (0-1)."""
    if len(member_account_ids) < 2:
        return 0.0
    membership = set(member_account_ids)
    response = supabase.table("edges").select("account_a_id, account_b_id, weight, edge_type").eq("run_id", run_id).eq("edge_type", "reciprocal_review").execute()
    edges = getattr(response, "data", response) or []
    pairs = set()
    for row in edges:
        a = str(row["account_a_id"])
        b = str(row["account_b_id"])
        if a in membership and b in membership:
            pairs.add(tuple(sorted((a, b))))

    total_pairs = len(member_account_ids) * (len(member_account_ids) - 1) / 2
    if total_pairs == 0:
        return 0.0
    return len(pairs) / total_pairs


def compute_collateral_score(member_account_ids: list[str], run_id: str) -> float:
    """1 - normalized(avg kyc_depth, avg account_age_days) across the
    cluster. Higher score = LESS at stake = riskier."""
    accounts = _load_accounts(member_account_ids, run_id)
    if not accounts:
        return 0.0

    avg_kyc = sum(int(a.get("kyc_depth", 0) or 0) for a in accounts) / len(accounts)
    avg_age = sum(int(a.get("account_age_days", 0) or 0) for a in accounts) / len(accounts)
    normalized_kyc = min(max(avg_kyc / 3.0, 0.0), 1.0)
    normalized_age = min(max(avg_age / 900.0, 0.0), 1.0)
    composite = (normalized_kyc + normalized_age) / 2.0
    return 1.0 - composite


def compute_proof_validity_ratio(member_account_ids: list[str], run_id: str) -> float:
    """Fraction of the cluster's transactions with proof_valid=True.
    (Used inverted as a feature: low validity ratio => risk signal.)"""
    if not member_account_ids:
        return 0.0
    response = supabase.table("transactions").select("id, proof_valid, buyer_account_id").eq("run_id", run_id).in_("buyer_account_id", member_account_ids).execute()
    tx_rows = getattr(response, "data", response) or []
    if not tx_rows:
        return 0.0
    valid = sum(1 for tx in tx_rows if tx.get("proof_valid") is True)
    return valid / len(tx_rows)


def compute_velocity_score(member_account_ids: list[str], run_id: str, tick: int) -> float:
    """Transactions+reviews per account in the last VELOCITY_WINDOW_TICKS
    (=5), normalized against the run's organic baseline rate."""
    if not member_account_ids:
        return 0.0
    lower_bound = max(0, tick - VELOCITY_WINDOW_TICKS)
    cluster_tx = supabase.table("transactions").select("id").eq("run_id", run_id).in_("buyer_account_id", member_account_ids).gte("tick", lower_bound).lte("tick", tick).execute()
    cluster_review = supabase.table("reviews").select("id").eq("run_id", run_id).in_("reviewer_account_id", member_account_ids).gte("tick", lower_bound).lte("tick", tick).execute()
    cluster_tx_count = len(getattr(cluster_tx, "data", cluster_tx) or [])
    cluster_review_count = len(getattr(cluster_review, "data", cluster_review) or [])
    cluster_rate = (cluster_tx_count + cluster_review_count) / max(len(member_account_ids), 1)

    organic_response = supabase.table("accounts").select("id").eq("run_id", run_id).eq("account_type", "organic").execute()
    organic_accounts = getattr(organic_response, "data", organic_response) or []
    if not organic_accounts:
        return cluster_rate

    organic_ids = [row["id"] for row in organic_accounts]
    organic_tx = supabase.table("transactions").select("id").eq("run_id", run_id).in_("buyer_account_id", organic_ids).gte("tick", lower_bound).lte("tick", tick).execute()
    organic_review = supabase.table("reviews").select("id").eq("run_id", run_id).in_("reviewer_account_id", organic_ids).gte("tick", lower_bound).lte("tick", tick).execute()
    organic_tx_count = len(getattr(organic_tx, "data", organic_tx) or [])
    organic_review_count = len(getattr(organic_review, "data", organic_review) or [])
    organic_baseline = (organic_tx_count + organic_review_count) / max(len(organic_ids), 1)
    if organic_baseline <= 0:
        return cluster_rate
    return cluster_rate / organic_baseline


def build_feature_vector(cluster_candidate: dict, run_id: str, tick: int) -> "np.ndarray":
    """Returns a 7-element np.ndarray in FEATURE_ORDER. This exact
    order is shared between train.py and hybrid_classifier.py —
    changing FEATURE_ORDER requires retraining model.pkl."""
    member_ids = cluster_candidate.get("member_account_ids", [])
    if not member_ids:
        return np.zeros(len(FEATURE_ORDER), dtype=float)

    reciprocity = compute_reciprocity_score(member_ids, run_id)
    collateral = compute_collateral_score(member_ids, run_id)
    proof_validity_ratio = compute_proof_validity_ratio(member_ids, run_id)
    velocity = compute_velocity_score(member_ids, run_id, tick)

    response = supabase.table("edges").select("account_a_id, account_b_id, weight").eq("run_id", run_id).eq("edge_type", "device_overlap").execute()
    edges = getattr(response, "data", response) or []
    device_overlap_max = 0.0
    for row in edges:
        a = str(row["account_a_id"])
        b = str(row["account_b_id"])
        if a in set(member_ids) and b in set(member_ids):
            device_overlap_max = max(device_overlap_max, _safe_float(row.get("weight"), 0.0))

    accounts = _load_accounts(member_ids, run_id)
    avg_age = sum(int(a.get("account_age_days", 0) or 0) for a in accounts) / max(len(accounts), 1)
    avg_account_age_inv = 1.0 - min(max(avg_age / 900.0, 0.0), 1.0)

    transaction_response = supabase.table("transactions").select("id, buyer_account_id").eq("run_id", run_id).in_("buyer_account_id", member_ids).execute()
    tx_rows = getattr(transaction_response, "data", transaction_response) or []
    total_transactions = len(tx_rows)
    reviews_without_tx = 0
    if member_ids:
        review_response = supabase.table("reviews").select("id, reviewer_account_id, transaction_id").eq("run_id", run_id).in_("reviewer_account_id", member_ids).execute()
        review_rows = getattr(review_response, "data", review_response) or []
        reviews_without_tx = sum(1 for row in review_rows if row.get("transaction_id") is None)
    review_to_purchase_ratio = (reviews_without_tx / total_transactions) if total_transactions else 0.0

    vector = np.array([
        reciprocity,
        collateral,
        1.0 - proof_validity_ratio,
        velocity,
        device_overlap_max,
        avg_account_age_inv,
        review_to_purchase_ratio,
    ], dtype=float)
    return vector
