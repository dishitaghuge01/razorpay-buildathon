create extension if not exists pgcrypto;

create table simulation_runs (
    id uuid primary key default gen_random_uuid(),
    run_label text not null,
    status text check (status in ('idle', 'running', 'completed', 'reset')) default 'idle',
    mode text check (mode in ('baseline', 'hybrid', 'both')) default 'both',
    tick integer default 0,
    started_at timestamptz,
    ended_at timestamptz,
    created_at timestamptz default now()
);

create table merchants (
    id uuid primary key default gen_random_uuid(),
    run_id uuid not null references simulation_runs(id) on delete cascade,
    name text not null,
    is_target boolean default false
);

create table rings (
    id uuid primary key default gen_random_uuid(),
    run_id uuid not null references simulation_runs(id) on delete cascade,
    attack_type text check (attack_type in ('sybil_flood', 'collusion_ring', 'whitewash_return')) not null,
    launched_tick integer not null,
    member_count integer default 0
);

create table accounts (
    id uuid primary key default gen_random_uuid(),
    run_id uuid not null references simulation_runs(id) on delete cascade,
    account_label text not null,
    account_type text check (account_type in ('organic', 'sybil', 'collusion_ring', 'whitewash')) default 'organic',
    ground_truth_ring_id uuid references rings(id),
    device_fingerprint text not null,
    ip_subnet text not null,
    payout_account text not null,
    kyc_depth integer check (kyc_depth between 0 and 3) default 1,
    account_age_days integer default 0,
    created_tick integer not null,
    created_at timestamptz default now()
);

create table transactions (
    id uuid primary key default gen_random_uuid(),
    run_id uuid not null references simulation_runs(id) on delete cascade,
    buyer_account_id uuid not null references accounts(id),
    merchant_id uuid not null references merchants(id),
    amount numeric(10,2) not null,
    status text check (status in ('completed', 'refund_requested', 'refund_held', 'refund_denied', 'refund_approved')) default 'completed',
    tick integer not null,
    proof_signature text,
    proof_public_key text,
    proof_valid boolean,
    created_at timestamptz default now()
);

create table reviews (
    id uuid primary key default gen_random_uuid(),
    run_id uuid not null references simulation_runs(id) on delete cascade,
    reviewer_account_id uuid not null references accounts(id),
    merchant_id uuid not null references merchants(id),
    transaction_id uuid references transactions(id),
    rating integer check (rating between 1 and 5),
    tick integer not null,
    created_at timestamptz default now()
);

create table edges (
    id uuid primary key default gen_random_uuid(),
    run_id uuid not null references simulation_runs(id) on delete cascade,
    account_a_id uuid not null references accounts(id),
    account_b_id uuid not null references accounts(id),
    edge_type text check (edge_type in ('device_overlap', 'ip_overlap', 'payout_overlap', 'timing_correlation', 'reciprocal_review')) not null,
    weight numeric(5,4) not null,
    tick integer not null
);

create table clusters (
    id uuid primary key default gen_random_uuid(),
    run_id uuid not null references simulation_runs(id) on delete cascade,
    tick integer not null,
    member_account_ids uuid[] not null,
    reciprocity_score numeric(5,4),
    collateral_score numeric(5,4),
    proof_validity_ratio numeric(5,4),
    velocity_score numeric(5,4),
    confidence numeric(5,4),
    mode text check (mode in ('baseline', 'hybrid')) not null,
    status text check (status in ('monitoring', 'flagged', 'held', 'cleared')) default 'monitoring',
    created_at timestamptz default now()
);

create table detections (
    id uuid primary key default gen_random_uuid(),
    run_id uuid not null references simulation_runs(id) on delete cascade,
    cluster_id uuid references clusters(id),
    tick integer not null,
    event_type text check (event_type in ('flag', 'hold', 'clear', 'proof_reject')) not null,
    message text not null,
    feature_snapshot jsonb,
    created_at timestamptz default now()
);

create table metrics_snapshots (
    id uuid primary key default gen_random_uuid(),
    run_id uuid not null references simulation_runs(id) on delete cascade,
    tick integer not null,
    mode text check (mode in ('baseline', 'hybrid')) not null,
    attack_type text check (attack_type in ('sybil_flood', 'collusion_ring', 'whitewash_return')),
    true_positives integer default 0,
    false_positives integer default 0,
    false_negatives integer default 0,
    true_negatives integer default 0,
    precision numeric(5,4),
    recall numeric(5,4),
    f1 numeric(5,4),
    estimated_fp_cost numeric(10,2) default 0,
    attack_success_rate numeric(5,4),
    created_at timestamptz default now()
);

create table pqc_proofs (
    id uuid primary key default gen_random_uuid(),
    run_id uuid not null references simulation_runs(id) on delete cascade,
    transaction_id uuid not null references transactions(id),
    public_key text not null,
    signature text not null,
    payload_hash text not null,
    verified boolean not null,
    tamper_test boolean default false,
    created_at timestamptz default now()
);

alter publication supabase_realtime add table
  accounts, transactions, reviews, edges, clusters, detections, metrics_snapshots, pqc_proofs, simulation_runs;
