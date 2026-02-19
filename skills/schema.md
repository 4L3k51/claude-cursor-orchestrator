# Schema Phase - Supabase Guidance
<!--
  Build phase: schema
  This file is injected during database schema steps.
  Populate with guidance for: table creation, migrations, RLS policies,
  indexes, foreign keys, GRANT statements, idempotent DDL patterns.
-->

---
title: Use tsvector for Full-Text Search
impact: MEDIUM
impactDescription: 100x faster than LIKE, with ranking support
tags: full-text-search, tsvector, gin, search
---
## Use tsvector for Full-Text Search
LIKE with wildcards can't use indexes. Full-text search with tsvector is orders of magnitude faster.
**Incorrect (LIKE pattern matching):**
```sql
-- Cannot use index, scans all rows
select * from articles where content like '%postgresql%';
-- Case-insensitive makes it worse
select * from articles where lower(content) like '%postgresql%';
```
**Correct (full-text search with tsvector):**
```sql
-- Add tsvector column and index
alter table articles add column search_vector tsvector
  generated always as (to_tsvector('english', coalesce(title,'') || ' ' || coalesce(content,''))) stored;
create index articles_search_idx on articles using gin (search_vector);
-- Fast full-text search
select * from articles
where search_vector @@ to_tsquery('english', 'postgresql & performance');
-- With ranking
select *, ts_rank(search_vector, query) as rank
from articles, to_tsquery('english', 'postgresql') query
where search_vector @@ query
order by rank desc;
```
Search multiple terms:
```sql
-- AND: both terms required
to_tsquery('postgresql & performance')
-- OR: either term
to_tsquery('postgresql | mysql')
-- Prefix matching
to_tsquery('post:*')
```
Reference: [Full Text Search](https://supabase.com/docs/guides/database/full-text-search)

---
title: Index JSONB Columns for Efficient Querying
impact: MEDIUM
impactDescription: 10-100x faster JSONB queries with proper indexing
tags: jsonb, gin, indexes, json
---
## Index JSONB Columns for Efficient Querying
JSONB queries without indexes scan the entire table. Use GIN indexes for containment queries.
**Incorrect (no index on JSONB):**
```sql
create table products (
  id bigint primary key,
  attributes jsonb
);
-- Full table scan for every query
select * from products where attributes @> '{"color": "red"}';
select * from products where attributes->>'brand' = 'Nike';
```
**Correct (GIN index for JSONB):**
```sql
-- GIN index for containment operators (@>, ?, ?&, ?|)
create index products_attrs_gin on products using gin (attributes);
-- Now containment queries use the index
select * from products where attributes @> '{"color": "red"}';
-- For specific key lookups, use expression index
create index products_brand_idx on products ((attributes->>'brand'));
select * from products where attributes->>'brand' = 'Nike';
```
Choose the right operator class:
```sql
-- jsonb_ops (default): supports all operators, larger index
create index idx1 on products using gin (attributes);
-- jsonb_path_ops: only @> operator, but 2-3x smaller index
create index idx2 on products using gin (attributes jsonb_path_ops);
```
Reference: [JSONB Indexes](https://www.postgresql.org/docs/current/datatype-json.html#JSON-INDEXING)

---
title: Add Constraints Safely in Migrations
impact: HIGH
impactDescription: Prevents migration failures and enables idempotent schema changes
tags: constraints, migrations, schema, alter-table
---
## Add Constraints Safely in Migrations
PostgreSQL does not support `ADD CONSTRAINT IF NOT EXISTS`. Migrations using this syntax will fail.
**Incorrect (causes syntax error):**
```sql
-- ERROR: syntax error at or near "not" (SQLSTATE 42601)
alter table public.profiles
add constraint if not exists profiles_birthchart_id_unique unique (birthchart_id);
```
**Correct (idempotent constraint creation):**
```sql
-- Use DO block to check before adding
do $
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'profiles_birthchart_id_unique'
    and conrelid = 'public.profiles'::regclass
  ) then
    alter table public.profiles
    add constraint profiles_birthchart_id_unique unique (birthchart_id);
  end if;
end $;
```
For all constraint types:
```sql
-- Check constraints
do $
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'check_age_positive'
  ) then
    alter table users add constraint check_age_positive check (age > 0);
  end if;
end $;
-- Foreign keys
do $
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'profiles_birthchart_id_fkey'
  ) then
    alter table profiles
    add constraint profiles_birthchart_id_fkey
    foreign key (birthchart_id) references birthcharts(id);
  end if;
end $;
```
Check if constraint exists:
```sql
-- Query to check constraint existence
select conname, contype, pg_get_constraintdef(oid)
from pg_constraint
where conrelid = 'public.profiles'::regclass;
-- contype values:
-- 'p' = PRIMARY KEY
-- 'f' = FOREIGN KEY
-- 'u' = UNIQUE
-- 'c' = CHECK
```
Reference: [Constraints](https://www.postgresql.org/docs/current/ddl-constraints.html)

---
title: Choose Appropriate Data Types
impact: HIGH
impactDescription: 50% storage reduction, faster comparisons
tags: data-types, schema, storage, performance
---
## Choose Appropriate Data Types
Using the right data types reduces storage, improves query performance, and prevents bugs.
**Incorrect (wrong data types):**
```sql
create table users (
  id int,                    -- Will overflow at 2.1 billion
  email varchar(255),        -- Unnecessary length limit
  created_at timestamp,      -- Missing timezone info
  is_active varchar(5),      -- String for boolean
  price varchar(20)          -- String for numeric
);
```
**Correct (appropriate data types):**
```sql
create table users (
  id bigint generated always as identity primary key,  -- 9 quintillion max
  email text,                     -- No artificial limit, same performance as varchar
  created_at timestamptz,         -- Always store timezone-aware timestamps
  is_active boolean default true, -- 1 byte vs variable string length
  price numeric(10,2)             -- Exact decimal arithmetic
);
```
Key guidelines:
```sql
-- IDs: use bigint, not int (future-proofing)
-- Strings: use text, not varchar(n) unless constraint needed
-- Time: use timestamptz, not timestamp
-- Money: use numeric, not float (precision matters)
-- Enums: use text with check constraint or create enum type
```
Reference: [Data Types](https://www.postgresql.org/docs/current/datatype.html)

---
title: Index Foreign Key Columns
impact: HIGH
impactDescription: 10-100x faster JOINs and CASCADE operations
tags: foreign-key, indexes, joins, schema
---
## Index Foreign Key Columns
Postgres does not automatically index foreign key columns. Missing indexes cause slow JOINs and CASCADE operations.
**Incorrect (unindexed foreign key):**
```sql
create table orders (
  id bigint generated always as identity primary key,
  customer_id bigint references customers(id) on delete cascade,
  total numeric(10,2)
);
-- No index on customer_id!
-- JOINs and ON DELETE CASCADE both require full table scan
select * from orders where customer_id = 123;  -- Seq Scan
delete from customers where id = 123;          -- Locks table, scans all orders
```
**Correct (indexed foreign key):**
```sql
create table orders (
  id bigint generated always as identity primary key,
  customer_id bigint references customers(id) on delete cascade,
  total numeric(10,2)
);
-- Always index the FK column
create index orders_customer_id_idx on orders (customer_id);
-- Now JOINs and cascades are fast
select * from orders where customer_id = 123;  -- Index Scan
delete from customers where id = 123;          -- Uses index, fast cascade
```
Find missing FK indexes:
```sql
select
  conrelid::regclass as table_name,
  a.attname as fk_column
from pg_constraint c
join pg_attribute a on a.attrelid = c.conrelid and a.attnum = any(c.conkey)
where c.contype = 'f'
  and not exists (
    select 1 from pg_index i
    where i.indrelid = c.conrelid and a.attnum = any(i.indkey)
  );
```
Reference: [Foreign Keys](https://www.postgresql.org/docs/current/ddl-constraints.html#DDL-CONSTRAINTS-FK)

---
title: Use Lowercase Identifiers for Compatibility
impact: MEDIUM
impactDescription: Avoid case-sensitivity bugs with tools, ORMs, and AI assistants
tags: naming, identifiers, case-sensitivity, schema, conventions
---
## Use Lowercase Identifiers for Compatibility
PostgreSQL folds unquoted identifiers to lowercase. Quoted mixed-case identifiers require quotes forever and cause issues with tools, ORMs, and AI assistants that may not recognize them.
**Incorrect (mixed-case identifiers):**
```sql
-- Quoted identifiers preserve case but require quotes everywhere
CREATE TABLE "Users" (
  "userId" bigint PRIMARY KEY,
  "firstName" text,
  "lastName" text
);
-- Must always quote or queries fail
SELECT "firstName" FROM "Users" WHERE "userId" = 1;
-- This fails - Users becomes users without quotes
SELECT firstName FROM Users;
-- ERROR: relation "users" does not exist
```
**Correct (lowercase snake_case):**
```sql
-- Unquoted lowercase identifiers are portable and tool-friendly
CREATE TABLE users (
  user_id bigint PRIMARY KEY,
  first_name text,
  last_name text
);
-- Works without quotes, recognized by all tools
SELECT first_name FROM users WHERE user_id = 1;
```
Common sources of mixed-case identifiers:
```sql
-- ORMs often generate quoted camelCase - configure them to use snake_case
-- Migrations from other databases may preserve original casing
-- Some GUI tools quote identifiers by default - disable this
-- If stuck with mixed-case, create views as a compatibility layer
CREATE VIEW users AS SELECT "userId" AS user_id, "firstName" AS first_name FROM "Users";
```
Reference: [Identifiers and Key Words](https://www.postgresql.org/docs/current/sql-syntax-lexical.html#SQL-SYNTAX-IDENTIFIERS)

---
title: Partition Large Tables for Better Performance
impact: MEDIUM-HIGH
impactDescription: 5-20x faster queries and maintenance on large tables
tags: partitioning, large-tables, time-series, performance
---
## Partition Large Tables for Better Performance
Partitioning splits a large table into smaller pieces, improving query performance and maintenance operations.
**Incorrect (single large table):**
```sql
create table events (
  id bigint generated always as identity,
  created_at timestamptz,
  data jsonb
);
-- 500M rows, queries scan everything
select * from events where created_at > '2024-01-01';  -- Slow
vacuum events;  -- Takes hours, locks table
```
**Correct (partitioned by time range):**
```sql
create table events (
  id bigint generated always as identity,
  created_at timestamptz not null,
  data jsonb
) partition by range (created_at);
-- Create partitions for each month
create table events_2024_01 partition of events
  for values from ('2024-01-01') to ('2024-02-01');
create table events_2024_02 partition of events
  for values from ('2024-02-01') to ('2024-03-01');
-- Queries only scan relevant partitions
select * from events where created_at > '2024-01-15';  -- Only scans events_2024_01+
-- Drop old data instantly
drop table events_2023_01;  -- Instant vs DELETE taking hours
```
When to partition:
- Tables > 100M rows
- Time-series data with date-based queries
- Need to efficiently drop old data
Reference: [Table Partitioning](https://www.postgresql.org/docs/current/ddl-partitioning.html)

---
title: Select Optimal Primary Key Strategy
impact: HIGH
impactDescription: Better index locality, reduced fragmentation
tags: primary-key, identity, uuid, serial, schema
---
## Select Optimal Primary Key Strategy
Primary key choice affects insert performance, index size, and replication
efficiency.
**Incorrect (problematic PK choices):**
```sql
-- identity is the SQL-standard approach
create table users (
  id serial primary key  -- Works, but IDENTITY is recommended
);
-- Random UUIDs (v4) cause index fragmentation
create table orders (
  id uuid default gen_random_uuid() primary key  -- UUIDv4 = random = scattered inserts
);
```
**Correct (optimal PK strategies):**
```sql
-- Use IDENTITY for sequential IDs (SQL-standard, best for most cases)
create table users (
  id bigint generated always as identity primary key
);
-- For distributed systems needing UUIDs, use UUIDv7 (time-ordered)
-- Requires pg_uuidv7 extension: create extension pg_uuidv7;
create table orders (
  id uuid default uuid_generate_v7() primary key  -- Time-ordered, no fragmentation
);
-- Alternative: time-prefixed IDs for sortable, distributed IDs (no extension needed)
create table events (
  id text default concat(
    to_char(now() at time zone 'utc', 'YYYYMMDDHH24MISSMS'),
    gen_random_uuid()::text
  ) primary key
);
```
Guidelines:
- Single database: `bigint identity` (sequential, 8 bytes, SQL-standard)
- Distributed/exposed IDs: UUIDv7 (requires pg_uuidv7) or ULID (time-ordered, no
  fragmentation)
- `serial` works but `identity` is SQL-standard and preferred for new
  applications
- Avoid random UUIDs (v4) as primary keys on large tables (causes index
  fragmentation)
Reference:
[Identity Columns](https://www.postgresql.org/docs/current/sql-createtable.html#SQL-CREATETABLE-PARMS-GENERATED-IDENTITY)

---
title: Apply Principle of Least Privilege
impact: MEDIUM
impactDescription: Reduced attack surface, better audit trail
tags: privileges, security, roles, permissions
---
## Apply Principle of Least Privilege
Grant only the minimum permissions required. Never use superuser for application queries.
**Incorrect (overly broad permissions):**
```sql
-- Application uses superuser connection
-- Or grants ALL to application role
grant all privileges on all tables in schema public to app_user;
grant all privileges on all sequences in schema public to app_user;
-- Any SQL injection becomes catastrophic
-- drop table users; cascades to everything
```
**Correct (minimal, specific grants):**
```sql
-- Create role with no default privileges
create role app_readonly nologin;
-- Grant only SELECT on specific tables
grant usage on schema public to app_readonly;
grant select on public.products, public.categories to app_readonly;
-- Create role for writes with limited scope
create role app_writer nologin;
grant usage on schema public to app_writer;
grant select, insert, update on public.orders to app_writer;
grant usage on sequence orders_id_seq to app_writer;
-- No DELETE permission
-- Login role inherits from these
create role app_user login password 'xxx';
grant app_writer to app_user;
```
Revoke public defaults:
```sql
-- Revoke default public access
revoke all on schema public from public;
revoke all on all tables in schema public from public;
```
Reference: [Roles and Privileges](https://supabase.com/blog/postgres-roles-and-privileges)

---
title: Enable Row Level Security for Multi-Tenant Data
impact: CRITICAL
impactDescription: Database-enforced tenant isolation, prevent data leaks
tags: rls, row-level-security, multi-tenant, security
---
## Enable Row Level Security for Multi-Tenant Data
Row Level Security (RLS) enforces data access at the database level, ensuring users only see their own data.
**Incorrect (application-level filtering only):**
```sql
-- Relying only on application to filter
select * from orders where user_id = $current_user_id;
-- Bug or bypass means all data is exposed!
select * from orders;  -- Returns ALL orders
```
**Correct (database-enforced RLS):**
```sql
-- Enable RLS on the table
alter table orders enable row level security;
-- Create policy for users to see only their orders
create policy orders_user_policy on orders
  for all
  using (user_id = current_setting('app.current_user_id')::bigint);
-- Force RLS even for table owners
alter table orders force row level security;
-- Set user context and query
set app.current_user_id = '123';
select * from orders;  -- Only returns orders for user 123
```
Policy for authenticated role:
```sql
create policy orders_user_policy on orders
  for all
  to authenticated
  using (user_id = auth.uid());
```
Reference: [Row Level Security](https://supabase.com/docs/guides/database/postgres/row-level-security)

---
title: Optimize RLS Policies for Performance
impact: HIGH
impactDescription: 5-10x faster RLS queries with proper patterns
tags: rls, performance, security, optimization
---
## Optimize RLS Policies for Performance
Poorly written RLS policies can cause severe performance issues. Use subqueries and indexes strategically.
**Incorrect (function called for every row):**
```sql
create policy orders_policy on orders
  using (auth.uid() = user_id);  -- auth.uid() called per row!
-- With 1M rows, auth.uid() is called 1M times
```
**Correct (wrap functions in SELECT):**
```sql
create policy orders_policy on orders
  using ((select auth.uid()) = user_id);  -- Called once, cached
-- 100x+ faster on large tables
```
Use security definer functions for complex checks:
```sql
-- Create helper function (runs as definer, bypasses RLS)
create or replace function is_team_member(team_id bigint)
returns boolean
language sql
security definer
set search_path = ''
as $
  select exists (
    select 1 from public.team_members
    where team_id = $1 and user_id = (select auth.uid())
  );
$;
-- Use in policy (indexed lookup, not per-row check)
create policy team_orders_policy on orders
  using ((select is_team_member(team_id)));
```
Always add indexes on columns used in RLS policies:
```sql
create index orders_user_id_idx on orders (user_id);
```
Reference: [RLS Performance](https://supabase.com/docs/guides/database/postgres/row-level-security#rls-performance-recommendations)
