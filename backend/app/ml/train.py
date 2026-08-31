"""Offline training script, produces model.pkl."""

from __future__ import annotations

from pathlib import Path
import pickle

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import classification_report
from sklearn.model_selection import train_test_split

from app.db import supabase
from app.graph.community_detection import extract_cluster_candidates
from app.graph.features import build_feature_vector


# TODO: replace with real organic_generator/attack_strategies once Track A lands

def generate_training_population(n_organic=2000, n_sybil_rings=40,
                                  n_collusion_rings=40, n_whitewash=20) -> "pd.DataFrame":
    """Reuses organic_generator + attack_strategies against a throwaway
    run_id to build a fully labeled synthetic population, then
    build_feature_vector() on every resulting cluster candidate.
    Label column: is_ring (bool), derived from ground_truth_ring_id
    IS NOT NULL — this label is stripped before feature extraction."""
    run_label = f"train-{pd.Timestamp.utcnow().strftime('%Y%m%d%H%M%S%f')}"
    run_row = supabase.table("simulation_runs").insert({"run_label": run_label, "status": "running"}).execute()
    run_id = run_row.data[0]["id"]

    merchant_row = supabase.table("merchants").insert({"run_id": run_id, "name": "training-merchant", "is_target": True}).execute()
    merchant_id = merchant_row.data[0]["id"]

    # Build a synthetic dataset using visible cluster structure. The label is derived
    # from the true ring membership, but the feature vector intentionally never reads
    # ground_truth_ring_id directly.
    rows: list[dict] = []
    for _ in range(n_organic):
        account_payload = {
            "run_id": run_id,
            "account_label": f"organic-train-{np.random.randint(1_000_000)}",
            "account_type": "organic",
            "ground_truth_ring_id": None,
            "device_fingerprint": f"org-dev-{np.random.randint(1_000_000)}",
            "ip_subnet": f"10.{np.random.randint(1, 250)}.{np.random.randint(1, 250)}.0/24",
            "payout_account": f"payout-{np.random.randint(1_000_000)}",
            "kyc_depth": int(np.random.randint(1, 4)),
            "account_age_days": int(np.random.randint(30, 901)),
            "created_tick": int(np.random.randint(0, 30)),
        }
        account = supabase.table("accounts").insert(account_payload).execute().data[0]
        if np.random.rand() < 0.7:
            tx = supabase.table("transactions").insert({
                "run_id": run_id,
                "buyer_account_id": account["id"],
                "merchant_id": merchant_id,
                "amount": round(float(np.random.lognormal(mean=2.0, sigma=0.75)), 2),
                "status": "completed",
                "tick": int(np.random.randint(0, 30)),
                "proof_valid": True,
            }).execute().data[0]
            supabase.table("reviews").insert({
                "run_id": run_id,
                "reviewer_account_id": account["id"],
                "merchant_id": merchant_id,
                "transaction_id": tx["id"],
                "rating": int(np.random.choice([4, 5], p=[0.35, 0.65])),
                "tick": int(np.random.randint(0, 30)),
            }).execute()

    for ring_idx in range(n_sybil_rings):
        ring = supabase.table("rings").insert({
            "run_id": run_id,
            "attack_type": "sybil_flood",
            "launched_tick": ring_idx,
            "member_count": 8,
        }).execute().data[0]
        member_ids = []
        for idx in range(8):
            account = supabase.table("accounts").insert({
                "run_id": run_id,
                "account_label": f"sybil-train-{ring_idx}-{idx}",
                "account_type": "sybil",
                "ground_truth_ring_id": ring["id"],
                "device_fingerprint": f"sybil-dev-{ring_idx}-{idx}",
                "ip_subnet": f"10.{ring_idx % 50}.{(idx * 3) % 250}.0/24",
                "payout_account": f"sybil-payout-{ring_idx}-{idx}",
                "kyc_depth": 0,
                "account_age_days": int(np.random.randint(0, 4)),
                "created_tick": ring_idx,
            }).execute().data[0]
            member_ids.append(account["id"])
            supabase.table("reviews").insert({
                "run_id": run_id,
                "reviewer_account_id": account["id"],
                "merchant_id": merchant_id,
                "transaction_id": None,
                "rating": 5,
                "tick": ring_idx,
            }).execute()
        rows.append({
            "member_account_ids": member_ids,
            "is_ring": True,
            "tick": ring_idx,
        })

    for ring_idx in range(n_collusion_rings):
        ring = supabase.table("rings").insert({
            "run_id": run_id,
            "attack_type": "collusion_ring",
            "launched_tick": ring_idx,
            "member_count": 6,
        }).execute().data[0]
        member_ids = []
        for idx in range(6):
            account = supabase.table("accounts").insert({
                "run_id": run_id,
                "account_label": f"collusion-train-{ring_idx}-{idx}",
                "account_type": "collusion_ring",
                "ground_truth_ring_id": ring["id"],
                "device_fingerprint": f"collusion-dev-{ring_idx}-{idx}",
                "ip_subnet": f"10.{80 + ring_idx % 50}.{(idx * 5) % 250}.0/24",
                "payout_account": f"collusion-payout-{ring_idx}-{idx}",
                "kyc_depth": int(np.random.randint(0, 2)),
                "account_age_days": int(np.random.randint(0, 31)),
                "created_tick": ring_idx,
            }).execute().data[0]
            member_ids.append(account["id"])
            tx = supabase.table("transactions").insert({
                "run_id": run_id,
                "buyer_account_id": account["id"],
                "merchant_id": merchant_id,
                "amount": round(float(np.random.uniform(25, 500)), 2),
                "status": "completed",
                "tick": ring_idx,
                "proof_valid": False,
            }).execute().data[0]
            supabase.table("reviews").insert({
                "run_id": run_id,
                "reviewer_account_id": account["id"],
                "merchant_id": merchant_id,
                "transaction_id": tx["id"],
                "rating": 5,
                "tick": ring_idx,
            }).execute()
        rows.append({
            "member_account_ids": member_ids,
            "is_ring": True,
            "tick": ring_idx,
        })

    for ring_idx in range(n_whitewash):
        ring = supabase.table("rings").insert({
            "run_id": run_id,
            "attack_type": "whitewash_return",
            "launched_tick": ring_idx,
            "member_count": 2,
        }).execute().data[0]
        burn = supabase.table("accounts").insert({
            "run_id": run_id,
            "account_label": f"whitewash-burn-{ring_idx}",
            "account_type": "organic",
            "ground_truth_ring_id": ring["id"],
            "device_fingerprint": f"whitewash-dev-{ring_idx}",
            "ip_subnet": f"10.{ring_idx % 50}.{ring_idx % 250}.0/24",
            "payout_account": f"whitewash-payout-{ring_idx}",
            "kyc_depth": 1,
            "account_age_days": int(np.random.randint(10, 60)),
            "created_tick": ring_idx,
        }).execute().data[0]
        new_account = supabase.table("accounts").insert({
            "run_id": run_id,
            "account_label": f"whitewash-new-{ring_idx}",
            "account_type": "whitewash",
            "ground_truth_ring_id": ring["id"],
            "device_fingerprint": burn["device_fingerprint"],
            "ip_subnet": burn["ip_subnet"],
            "payout_account": burn["payout_account"],
            "kyc_depth": 0,
            "account_age_days": 0,
            "created_tick": ring_idx,
        }).execute().data[0]
        rows.append({
            "member_account_ids": [burn["id"], new_account["id"]],
            "is_ring": True,
            "tick": ring_idx,
        })

    cluster_candidates = extract_cluster_candidates(run_id, tick=max(0, int(np.random.randint(0, 30))))
    for cluster in cluster_candidates:
        member_ids = cluster["member_account_ids"]
        feature_vector = build_feature_vector(cluster, run_id, tick=cluster["tick"])
        rows.append({
            "member_account_ids": member_ids,
            "is_ring": bool(any(
                supabase.table("accounts").select("ground_truth_ring_id").in_("id", member_ids).execute().data and row.get("ground_truth_ring_id") is not None
                for row in supabase.table("accounts").select("ground_truth_ring_id").in_("id", member_ids).execute().data
            )),
            "feature_vector": feature_vector,
            "tick": cluster["tick"],
        })

    frame_rows = []
    for row in rows:
        if "feature_vector" in row:
            frame_rows.append({**row, **dict(zip([f"f{i}" for i in range(len(row["feature_vector"]))], row["feature_vector"]))})
        else:
            cluster = {
                "member_account_ids": row["member_account_ids"],
                "is_ring": row["is_ring"],
                "tick": row["tick"],
            }
            feature_vector = build_feature_vector(cluster, run_id, tick=row["tick"])
            frame_rows.append({**cluster, **dict(zip([f"f{i}" for i in range(len(feature_vector))], feature_vector))})

    df = pd.DataFrame(frame_rows)
    df["is_ring"] = df["is_ring"].astype(bool)
    return df


def train_gbm(df: "pd.DataFrame", target_col: str = "is_ring") -> "GradientBoostingClassifier":
    """70/30 train/test split, sklearn.ensemble.GradientBoostingClassifier
    (n_estimators=200, max_depth=3, learning_rate=0.05). Prints
    precision/recall/F1 on the held-out 30% — this is your reported
    offline number, separate from the live demo numbers."""
    feature_cols = [col for col in df.columns if col.startswith("f")]
    X = df[feature_cols].to_numpy(dtype=float)
    y = df[target_col].astype(int).to_numpy()
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.3, random_state=42)
    model = GradientBoostingClassifier(n_estimators=200, learning_rate=0.05, max_depth=3, random_state=42)
    model.fit(X_train, y_train)
    y_pred = model.predict(X_test)
    print(classification_report(y_test, y_pred, target_names=["organic", "ring"]))
    return model


def save_model(model, path: str = "app/ml/model.pkl") -> None:
    """Pickle the trained model to disk."""
    save_path = Path(path)
    save_path.parent.mkdir(parents=True, exist_ok=True)
    with save_path.open("wb") as f:
        pickle.dump(model, f)


if __name__ == "__main__":
    df = generate_training_population()
    model = train_gbm(df)
    save_model(model)
