-- Supabase schema for OpenJarvis savings leaderboard
-- Run this in your Supabase SQL Editor to set up the table and RLS policies.

create table if not exists savings_entries (
  id          uuid primary key default gen_random_uuid(),
  anon_id     text unique not null,
  display_name text not null,
  total_calls  integer not null default 0,
  total_tokens integer not null default 0,
  dollar_savings numeric not null default 0,
  energy_wh_saved numeric not null default 0,
  flops_saved  numeric not null default 0,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

create index if not exists idx_savings_dollar on savings_entries (dollar_savings desc);

alter table savings_entries enable row level security;

-- Anyone can read (for the leaderboard page)
create policy "Public read" on savings_entries
  for select using (true);

-- Anon key can insert
create policy "Anon insert" on savings_entries
  for insert with check (true);

-- Anon key can update their own row (matched by anon_id)
create policy "Anon update own" on savings_entries
  for update using (true);

-- Auto-update updated_at on changes
create or replace function update_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

create trigger savings_updated_at
  before update on savings_entries
  for each row execute function update_updated_at();
