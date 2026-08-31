import uuid

import pytest

from app.db import supabase
from app.simulation.organic_generator import (
    generate_organic_account,
    generate_organic_review,
    generate_organic_transaction,
    run_organic_tick,
)


@pytest.fixture
def run_with_merchant():
    run_label = f"organic-test-{uuid.uuid4().hex[:8]}"
    run_row = supabase.table("simulation_runs").insert({"run_label": run_label}).execute()
    run_id = run_row.data[0]["id"]
    merchant_row = supabase.table("merchants").insert({"run_id": run_id, "name": f"merchant-{uuid.uuid4().hex[:8]}", "is_target": True}).execute()
    merchant_id = merchant_row.data[0]["id"]

    yield run_id, merchant_id

    supabase.table("simulation_runs").delete().eq("id", run_id).execute()


def test_generate_organic_account(run_with_merchant):
    run_id, _ = run_with_merchant
    row = generate_organic_account(run_id, tick=1)

    assert row["account_type"] == "organic"
    assert row["ground_truth_ring_id"] is None
    assert row["kyc_depth"] in {1, 2, 3}
    assert 30 <= row["account_age_days"] <= 900
    assert row["device_fingerprint"]
    assert row["ip_subnet"]
    assert row["payout_account"]


def test_generate_organic_transaction_and_review(run_with_merchant):
    run_id, merchant_id = run_with_merchant
    account_row = generate_organic_account(run_id, tick=2)

    tx = generate_organic_transaction(run_id, account_row["id"], merchant_id, tick=2)
    assert tx["status"] == "completed"
    assert float(tx["amount"]) > 0
    assert tx["run_id"] == run_id
    assert "proof_signature" in tx
    assert "proof_public_key" in tx

    review = generate_organic_review(run_id, account_row["id"], merchant_id, tx["id"], tick=2)
    assert review["rating"] in range(1, 6)
    assert review["transaction_id"] == tx["id"]
    assert review["merchant_id"] == merchant_id


def test_run_organic_tick_creates_activity(run_with_merchant):
    run_id, _ = run_with_merchant
    run_organic_tick(run_id, tick=3, new_accounts_per_tick=2, tx_per_tick=2)

    accounts = supabase.table("accounts").select("*").eq("run_id", run_id).eq("account_type", "organic").execute()
    reviews = supabase.table("reviews").select("*").eq("run_id", run_id).execute()
    txs = supabase.table("transactions").select("*").eq("run_id", run_id).execute()

    assert len(accounts.data) >= 2
    assert len(txs.data) >= 2
    assert len(reviews.data) >= 2
