-- Run once in the new Supabase Free project's SQL editor (or apply as a migration).
-- No public grants. The Flask backend checks the owner and uses a server-only key.
create table if not exists public.pluxee_state (
  user_id uuid primary key references auth.users(id) on delete cascade,
  state jsonb not null,
  updated_at timestamptz not null default now()
);
create table if not exists public.pluxee_ledger (
  user_id uuid primary key references auth.users(id) on delete cascade,
  transactions jsonb not null default '[]'::jsonb,
  updated_at timestamptz not null default now()
);
create table if not exists public.pluxee_sessions (
  token_hash text primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  csrf_token text not null,
  expires_at timestamptz not null,
  created_at timestamptz not null default now()
);
create index if not exists pluxee_sessions_expiry on public.pluxee_sessions(expires_at);
create table if not exists public.pluxee_login_limits (
  client_hash text primary key,
  attempts integer not null default 1,
  window_start timestamptz not null default now()
);
alter table public.pluxee_state enable row level security;
alter table public.pluxee_ledger enable row level security;
alter table public.pluxee_sessions enable row level security;
alter table public.pluxee_login_limits enable row level security;
revoke all on public.pluxee_state, public.pluxee_ledger, public.pluxee_sessions, public.pluxee_login_limits from anon, authenticated;
grant all on public.pluxee_state, public.pluxee_ledger, public.pluxee_sessions, public.pluxee_login_limits to service_role;
-- Owner policies are defense in depth if authenticated SELECT is enabled later.
drop policy if exists owner_state on public.pluxee_state;
create policy owner_state on public.pluxee_state for select to authenticated using ((select auth.uid()) = user_id);
drop policy if exists owner_ledger on public.pluxee_ledger;
create policy owner_ledger on public.pluxee_ledger for select to authenticated using ((select auth.uid()) = user_id);
-- Atomic, shared rate limit across workers. No IP addresses or emails stored.
create or replace function public.pluxee_login_allowed(client_hash_input text)
returns boolean language plpgsql security invoker set search_path = public as $$
declare current_attempts integer;
begin
  delete from public.pluxee_login_limits where window_start < now() - interval '1 day';
  insert into public.pluxee_login_limits (client_hash, attempts, window_start)
    values (client_hash_input, 1, now())
  on conflict (client_hash) do update set
    attempts = case when pluxee_login_limits.window_start < now() - interval '15 minutes' then 1 else pluxee_login_limits.attempts + 1 end,
    window_start = case when pluxee_login_limits.window_start < now() - interval '15 minutes' then now() else pluxee_login_limits.window_start end
  returning attempts into current_attempts;
  return current_attempts <= 8;
end;
$$;
revoke all on function public.pluxee_login_allowed(text) from public, anon, authenticated;
grant execute on function public.pluxee_login_allowed(text) to service_role;
create table if not exists public.pluxee_push_subscriptions (
  endpoint_hash text primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  session_hash text not null references public.pluxee_sessions(token_hash) on delete cascade,
  expires_at timestamptz not null,
  subscription jsonb not null
);
alter table public.pluxee_push_subscriptions enable row level security;
revoke all on public.pluxee_push_subscriptions from anon, authenticated;
grant all on public.pluxee_push_subscriptions to service_role;
