alter table simulation_runs enable row level security;
create policy "anon_can_select_all" on simulation_runs for select using (true);

alter table accounts enable row level security;
create policy "anon_can_select_all" on accounts for select using (true);

alter table transactions enable row level security;
create policy "anon_can_select_all" on transactions for select using (true);

alter table reviews enable row level security;
create policy "anon_can_select_all" on reviews for select using (true);

alter table edges enable row level security;
create policy "anon_can_select_all" on edges for select using (true);

alter table clusters enable row level security;
create policy "anon_can_select_all" on clusters for select using (true);

alter table detections enable row level security;
create policy "anon_can_select_all" on detections for select using (true);

alter table metrics_snapshots enable row level security;
create policy "anon_can_select_all" on metrics_snapshots for select using (true);

alter table pqc_proofs enable row level security;
create policy "anon_can_select_all" on pqc_proofs for select using (true);
