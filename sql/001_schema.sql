-- Fixtures and final scores for the app.
-- Apply in the Supabase SQL editor. ETL uses the service role (bypasses RLS).

create table if not exists public.teams (
  abbr text primary key,
  full_name text,
  conference text,
  division text
);

create table if not exists public.games (
  game_id text primary key,
  season integer not null,
  week integer not null,
  game_type text not null,
  kickoff_at timestamptz,
  home_team text not null references public.teams (abbr),
  away_team text not null references public.teams (abbr),
  home_score integer,
  away_score integer,
  status text not null check (status in ('scheduled', 'final')),
  overtime boolean,
  location text,
  stadium text,
  spread_line numeric,
  total_line numeric,
  espn_id text,
  updated_at timestamptz not null default now()
);

create index if not exists games_season_week_idx on public.games (season, week);
create index if not exists games_status_kickoff_idx on public.games (status, kickoff_at);
create index if not exists games_home_team_idx on public.games (home_team);
create index if not exists games_away_team_idx on public.games (away_team);

create or replace view public.fixtures
  with (security_invoker = true)
as
select * from public.games
where status = 'scheduled';

create or replace view public.results
  with (security_invoker = true)
as
select * from public.games
where status = 'final';

alter table public.teams enable row level security;
alter table public.games enable row level security;

drop policy if exists "public read teams" on public.teams;
create policy "public read teams"
  on public.teams
  for select
  to anon, authenticated
  using (true);

drop policy if exists "public read games" on public.games;
create policy "public read games"
  on public.games
  for select
  to anon, authenticated
  using (true);

grant select on public.teams, public.games, public.fixtures, public.results
  to anon, authenticated;
