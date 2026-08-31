import uuid

import pytest

from app.db import supabase
from app.simulation.attack_strategies import (
    REFUND_DELAY_TICKS,
    launch_collusion_ring,
    launch_sybil_flood,
    launch_whitewash_return,
)


@pytest.fixture
def run_with_merchant():
    run_label = f"attack-test-{uuid.uuid4().hex[:8]}"
    run_row = supabase.table("simulation_runs").insert({"run_label": run_label}).execute()
    run_id = run_row.data[0]["id"]
    merchant_row = supabase.table("merchants").insert({"run_id": run_id, "name": f"merchant-{uuid.uuid4().hex[:8]}", "is_target": True}).execute()
    merchant_id = merchant_row.data[0]["id"]

    yield run_id, merchant_id

    supabase.table("simulation_runs").delete().eq("id", run_id).execute()


def test_launch_sybil_flood_creates_ring(run_with_merchant):
    run_id, merchant_id = run_with_merchant
    ring_row = launch_sybil_flood(run_id, merchant_id, tick=10, ring_size=8)

    assert ring_row["attack_type"] == "sybil_flood"
    assert ring_row["member_count"] == 8
    assert ring_row["run_id"] == run_id

    accounts = supabase.table("accounts").select("*").eq("run_id", run_id).eq("account_type", "sybil").execute()
    assert len(accounts.data) == 8
    for account in accounts.data:
        assert account["ground_truth_ring_id"] == ring_row["id"]
        assert account["kyc_depth"] == 0
        assert account["account_age_days"] in {0, 1, 2, 3}

    unique_fingerprints = {row["device_fingerprint"] for row in accounts.data}
    unique_subnets = {row["ip_subnet"].split("/")[0] for row in accounts.data}
    shared_prefixes = {row["ip_subnet"].split("/")[0].rsplit(".", 1)[0] for row in accounts.data}
    assert len(unique_fingerprints) > 1
    assert len(unique_subnets) > 1
    assert len(shared_prefixes) == 1


def test_launch_collusion_ring_creates_ring_and_reviews(run_with_merchant):
    run_id, merchant_id = run_with_merchant
    ring_row = launch_collusion_ring(run_id, merchant_id, tick=11, ring_size=6)

    assert ring_row["attack_type"] == "collusion_ring"
    assert ring_row["member_count"] == 6
    assert ring_row["run_id"] == run_id
    assert ring_row["launched_tick"] == 11

    accounts = supabase.table("accounts").select("*").eq("run_id", run_id).eq("account_type", "collusion_ring").execute()
    txs = supabase.table("transactions").select("*").eq("run_id", run_id).execute()
    reviews = supabase.table("reviews").select("*").eq("run_id", run_id).execute()

    assert len(accounts.data) == 6
    assert len(txs.data) == 6
    assert len(reviews.data) == 6

    for account in accounts.data:
        assert account["ground_truth_ring_id"] == ring_row["id"]

    assert REFUND_DELAY_TICKS == 3


def test_launch_whitewash_return_marks_existing_and_spawns_new_account(run_with_merchant):
    run_id, merchant_id = run_with_merchant
    burn_account = supabase.table("accounts").insert({
        "run_id": run_id,
        "account_label": "burn-account",
        "account_type": "organic",
        "ground_truth_ring_id": None,
        "device_fingerprint": "burn-dev-001",
        "ip_subnet": "10.10.10.0/24",
        "payout_account": "burn-payout-001",
        "kyc_depth": 2,
        "account_age_days": 45,
        "created_tick": 5,
    }).execute().data[0]

    ring_row = launch_whitewash_return(run_id, merchant_id, tick=12, burn_account_id=burn_account["id"])

    assert ring_row["attack_type"] == "whitewash_return"
    assert ring_row["run_id"] == run_id

    updated_burn = supabase.table("accounts").select("*").eq("id", burn_account["id"]).execute().data[0]
    new_accounts = supabase.table("accounts").select("*").eq("run_id", run_id).eq("account_type", "whitewash").execute()

    spawned = next((row for row in new_accounts.data if row["id"] != burn_account["id"]), None)
    assert spawned is not None
    assert updated_burn["account_type"] == "whitewash"
    assert updated_burn["ground_truth_ring_id"] == ring_row["id"]
    assert len(new_accounts.data) == 2
    assert spawned["device_fingerprint"] == burn_account["device_fingerprint"]
    assert spawned["payout_account"] == burn_account["payout_account"]
    assert spawned["account_age_days"] == 0
