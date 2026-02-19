# Backend Phase - Supabase Guidance
<!--
  Build phase: backend
  This file is injected during backend/API implementation steps.
  Populate with guidance for: Edge Functions, API routes, authentication flows,
  realtime subscriptions, storage operations, server-side Supabase client usage.
-->

---
title: Configure Idle Connection Timeouts
impact: HIGH
impactDescription: Reclaim 30-50% of connection slots from idle clients
tags: connections, timeout, idle, resource-management
---
## Configure Idle Connection Timeouts
Idle connections waste resources. Configure timeouts to automatically reclaim them.
**Incorrect (connections held indefinitely):**
```sql
-- No timeout configured
show idle_in_transaction_session_timeout;  -- 0 (disabled)
-- Connections stay open forever, even when idle
select pid, state, state_change, query
from pg_stat_activity
where state = 'idle in transaction';
-- Shows transactions idle for hours, holding locks
```
**Correct (automatic cleanup of idle connections):**
```sql
-- Terminate connections idle in transaction after 30 seconds
alter system set idle_in_transaction_session_timeout = '30s';
-- Terminate completely idle connections after 10 minutes
alter system set idle_session_timeout = '10min';
-- Reload configuration
select pg_reload_conf();
```
For pooled connections, configure at the pooler level:
```ini
# pgbouncer.ini
server_idle_timeout = 60
client_idle_timeout = 300
```
Reference: [Connection Timeouts](https://www.postgresql.org/docs/current/runtime-config-client.html#GUC-IDLE-IN-TRANSACTION-SESSION-TIMEOUT)

---
title: Set Appropriate Connection Limits
impact: CRITICAL
impactDescription: Prevent database crashes and memory exhaustion
tags: connections, max-connections, limits, stability
---
## Set Appropriate Connection Limits
Too many connections exhaust memory and degrade performance. Set limits based on available resources.
**Incorrect (unlimited or excessive connections):**
```sql
-- Default max_connections = 100, but often increased blindly
show max_connections;  -- 500 (way too high for 4GB RAM)
-- Each connection uses 1-3MB RAM
-- 500 connections * 2MB = 1GB just for connections!
-- Out of memory errors under load
```
**Correct (calculate based on resources):**
```sql
-- Formula: max_connections = (RAM in MB / 5MB per connection) - reserved
-- For 4GB RAM: (4096 / 5) - 10 = ~800 theoretical max
-- But practically, 100-200 is better for query performance
-- Recommended settings for 4GB RAM
alter system set max_connections = 100;
-- Also set work_mem appropriately
-- work_mem * max_connections should not exceed 25% of RAM
alter system set work_mem = '8MB';  -- 8MB * 100 = 800MB max
```
Monitor connection usage:
```sql
select count(*), state from pg_stat_activity group by state;
```
Reference: [Database Connections](https://supabase.com/docs/platform/performance#connection-management)

---
title: Use Connection Pooling for All Applications
impact: CRITICAL
impactDescription: Handle 10-100x more concurrent users
tags: connection-pooling, pgbouncer, performance, scalability
---
## Use Connection Pooling for All Applications
Postgres connections are expensive (1-3MB RAM each). Without pooling, applications exhaust connections under load.
**Incorrect (new connection per request):**
```sql
-- Each request creates a new connection
-- Application code: db.connect() per request
-- Result: 500 concurrent users = 500 connections = crashed database
-- Check current connections
select count(*) from pg_stat_activity;  -- 487 connections!
```
**Correct (connection pooling):**
```sql
-- Use a pooler like PgBouncer between app and database
-- Application connects to pooler, pooler reuses a small pool to Postgres
-- Configure pool_size based on: (CPU cores * 2) + spindle_count
-- Example for 4 cores: pool_size = 10
-- Result: 500 concurrent users share 10 actual connections
select count(*) from pg_stat_activity;  -- 10 connections
```
Pool modes:
- **Transaction mode**: connection returned after each transaction (best for most apps)
- **Session mode**: connection held for entire session (needed for prepared statements, temp tables)
Reference: [Connection Pooling](https://supabase.com/docs/guides/database/connecting-to-postgres#connection-pooler)

---
title: Use Prepared Statements Correctly with Pooling
impact: HIGH
impactDescription: Avoid prepared statement conflicts in pooled environments
tags: prepared-statements, connection-pooling, transaction-mode
---
## Use Prepared Statements Correctly with Pooling
Prepared statements are tied to individual database connections. In transaction-mode pooling, connections are shared, causing conflicts.
**Incorrect (named prepared statements with transaction pooling):**
```sql
-- Named prepared statement
prepare get_user as select * from users where id = $1;
-- In transaction mode pooling, next request may get different connection
execute get_user(123);
-- ERROR: prepared statement "get_user" does not exist
```
**Correct (use unnamed statements or session mode):**
```sql
-- Option 1: Use unnamed prepared statements (most ORMs do this automatically)
-- The query is prepared and executed in a single protocol message
-- Option 2: Deallocate after use in transaction mode
prepare get_user as select * from users where id = $1;
execute get_user(123);
deallocate get_user;
-- Option 3: Use session mode pooling (port 5432 vs 6543)
-- Connection is held for entire session, prepared statements persist
```
Check your driver settings:
```sql
-- Many drivers use prepared statements by default
-- Node.js pg: { prepare: false } to disable
-- JDBC: prepareThreshold=0 to disable
```
Reference: [Prepared Statements with Pooling](https://supabase.com/docs/guides/database/connecting-to-postgres#connection-pool-modes)

---
title: Batch INSERT Statements for Bulk Data
impact: MEDIUM
impactDescription: 10-50x faster bulk inserts
tags: batch, insert, bulk, performance, copy
---
## Batch INSERT Statements for Bulk Data
Individual INSERT statements have high overhead. Batch multiple rows in single statements or use COPY.
**Incorrect (individual inserts):**
```sql
-- Each insert is a separate transaction and round trip
insert into events (user_id, action) values (1, 'click');
insert into events (user_id, action) values (1, 'view');
insert into events (user_id, action) values (2, 'click');
-- ... 1000 more individual inserts
-- 1000 inserts = 1000 round trips = slow
```
**Correct (batch insert):**
```sql
-- Multiple rows in single statement
insert into events (user_id, action) values
  (1, 'click'),
  (1, 'view'),
  (2, 'click'),
  -- ... up to ~1000 rows per batch
  (999, 'view');
-- One round trip for 1000 rows
```
For large imports, use COPY:
```sql
-- COPY is fastest for bulk loading
copy events (user_id, action, created_at)
from '/path/to/data.csv'
with (format csv, header true);
-- Or from stdin in application
copy events (user_id, action) from stdin with (format csv);
1,click
1,view
2,click
\.
```
Reference: [COPY](https://www.postgresql.org/docs/current/sql-copy.html)

---
title: Eliminate N+1 Queries with Batch Loading
impact: MEDIUM-HIGH
impactDescription: 10-100x fewer database round trips
tags: n-plus-one, batch, performance, queries
---
## Eliminate N+1 Queries with Batch Loading
N+1 queries execute one query per item in a loop. Batch them into a single query using arrays or JOINs.
**Incorrect (N+1 queries):**
```sql
-- First query: get all users
select id from users where active = true;  -- Returns 100 IDs
-- Then N queries, one per user
select * from orders where user_id = 1;
select * from orders where user_id = 2;
select * from orders where user_id = 3;
-- ... 97 more queries!
-- Total: 101 round trips to database
```
**Correct (single batch query):**
```sql
-- Collect IDs and query once with ANY
select * from orders where user_id = any(array[1, 2, 3, ...]);
-- Or use JOIN instead of loop
select u.id, u.name, o.*
from users u
left join orders o on o.user_id = u.id
where u.active = true;
-- Total: 1 round trip
```
Application pattern:
```sql
-- Instead of looping in application code:
-- for user in users: db.query("SELECT * FROM orders WHERE user_id = $1", user.id)
-- Pass array parameter:
select * from orders where user_id = any($1::bigint[]);
-- Application passes: [1, 2, 3, 4, 5, ...]
```
Reference: [N+1 Query Problem](https://supabase.com/docs/guides/database/query-optimization)

---
title: Use Cursor-Based Pagination Instead of OFFSET
impact: MEDIUM-HIGH
impactDescription: Consistent O(1) performance regardless of page depth
tags: pagination, cursor, keyset, offset, performance
---
## Use Cursor-Based Pagination Instead of OFFSET
OFFSET-based pagination scans all skipped rows, getting slower on deeper pages. Cursor pagination is O(1).
**Incorrect (OFFSET pagination):**
```sql
-- Page 1: scans 20 rows
select * from products order by id limit 20 offset 0;
-- Page 100: scans 2000 rows to skip 1980
select * from products order by id limit 20 offset 1980;
-- Page 10000: scans 200,000 rows!
select * from products order by id limit 20 offset 199980;
```
**Correct (cursor/keyset pagination):**
```sql
-- Page 1: get first 20
select * from products order by id limit 20;
-- Application stores last_id = 20
-- Page 2: start after last ID
select * from products where id > 20 order by id limit 20;
-- Uses index, always fast regardless of page depth
-- Page 10000: same speed as page 1
select * from products where id > 199980 order by id limit 20;
```
For multi-column sorting:
```sql
-- Cursor must include all sort columns
select * from products
where (created_at, id) > ('2024-01-15 10:00:00', 12345)
order by created_at, id
limit 20;
```
Reference: [Pagination](https://supabase.com/docs/guides/database/pagination)

---
title: Use UPSERT for Insert-or-Update Operations
impact: MEDIUM
impactDescription: Atomic operation, eliminates race conditions
tags: upsert, on-conflict, insert, update
---
## Use UPSERT for Insert-or-Update Operations
Using separate SELECT-then-INSERT/UPDATE creates race conditions. Use INSERT ... ON CONFLICT for atomic upserts.
**Incorrect (check-then-insert race condition):**
```sql
-- Race condition: two requests check simultaneously
select * from settings where user_id = 123 and key = 'theme';
-- Both find nothing
-- Both try to insert
insert into settings (user_id, key, value) values (123, 'theme', 'dark');
-- One succeeds, one fails with duplicate key error!
```
**Correct (atomic UPSERT):**
```sql
-- Single atomic operation
insert into settings (user_id, key, value)
values (123, 'theme', 'dark')
on conflict (user_id, key)
do update set value = excluded.value, updated_at = now();
-- Returns the inserted/updated row
insert into settings (user_id, key, value)
values (123, 'theme', 'dark')
on conflict (user_id, key)
do update set value = excluded.value
returning *;
```
Insert-or-ignore pattern:
```sql
-- Insert only if not exists (no update)
insert into page_views (page_id, user_id)
values (1, 123)
on conflict (page_id, user_id) do nothing;
```
Reference: [INSERT ON CONFLICT](https://www.postgresql.org/docs/current/sql-insert.html#SQL-ON-CONFLICT)

---
title: Use Advisory Locks for Application-Level Locking
impact: MEDIUM
impactDescription: Efficient coordination without row-level lock overhead
tags: advisory-locks, coordination, application-locks
---
## Use Advisory Locks for Application-Level Locking
Advisory locks provide application-level coordination without requiring database rows to lock.
**Incorrect (creating rows just for locking):**
```sql
-- Creating dummy rows to lock on
create table resource_locks (
  resource_name text primary key
);
insert into resource_locks values ('report_generator');
-- Lock by selecting the row
select * from resource_locks where resource_name = 'report_generator' for update;
```
**Correct (advisory locks):**
```sql
-- Session-level advisory lock (released on disconnect or unlock)
select pg_advisory_lock(hashtext('report_generator'));
-- ... do exclusive work ...
select pg_advisory_unlock(hashtext('report_generator'));
-- Transaction-level lock (released on commit/rollback)
begin;
select pg_advisory_xact_lock(hashtext('daily_report'));
-- ... do work ...
commit;  -- Lock automatically released
```
Try-lock for non-blocking operations:
```sql
-- Returns immediately with true/false instead of waiting
select pg_try_advisory_lock(hashtext('resource_name'));
-- Use in application
if (acquired) {
  -- Do work
  select pg_advisory_unlock(hashtext('resource_name'));
} else {
  -- Skip or retry later
}
```
Reference: [Advisory Locks](https://www.postgresql.org/docs/current/explicit-locking.html#ADVISORY-LOCKS)

---
title: Use SKIP LOCKED for Non-Blocking Queue Processing
impact: MEDIUM-HIGH
impactDescription: 10x throughput for worker queues
tags: skip-locked, queue, workers, concurrency
---
## Use SKIP LOCKED for Non-Blocking Queue Processing
When multiple workers process a queue, SKIP LOCKED allows workers to process different rows without waiting.
**Incorrect (workers block each other):**
```sql
-- Worker 1 and Worker 2 both try to get next job
begin;
select * from jobs where status = 'pending' order by created_at limit 1 for update;
-- Worker 2 waits for Worker 1's lock to release!
```
**Correct (SKIP LOCKED for parallel processing):**
```sql
-- Each worker skips locked rows and gets the next available
begin;
select * from jobs
where status = 'pending'
order by created_at
limit 1
for update skip locked;
-- Worker 1 gets job 1, Worker 2 gets job 2 (no waiting)
update jobs set status = 'processing' where id = $1;
commit;
```
Complete queue pattern:
```sql
-- Atomic claim-and-update in one statement
update jobs
set status = 'processing', worker_id = $1, started_at = now()
where id = (
  select id from jobs
  where status = 'pending'
  order by created_at
  limit 1
  for update skip locked
)
returning *;
```
Reference: [SELECT FOR UPDATE SKIP LOCKED](https://www.postgresql.org/docs/current/sql-select.html#SQL-FOR-UPDATE-SHARE)

---
title: Create Composite Indexes for Multi-Column Queries
impact: HIGH
impactDescription: 5-10x faster multi-column queries
tags: indexes, composite-index, multi-column, query-optimization
---
## Create Composite Indexes for Multi-Column Queries
When queries filter on multiple columns, a composite index is more efficient than separate single-column indexes.
**Incorrect (separate indexes require bitmap scan):**
```sql
-- Two separate indexes
create index orders_status_idx on orders (status);
create index orders_created_idx on orders (created_at);
-- Query must combine both indexes (slower)
select * from orders where status = 'pending' and created_at > '2024-01-01';
```
**Correct (composite index):**
```sql
-- Single composite index (leftmost column first for equality checks)
create index orders_status_created_idx on orders (status, created_at);
-- Query uses one efficient index scan
select * from orders where status = 'pending' and created_at > '2024-01-01';
```
**Column order matters** - place equality columns first, range columns last:
```sql
-- Good: status (=) before created_at (>)
create index idx on orders (status, created_at);
-- Works for: WHERE status = 'pending'
-- Works for: WHERE status = 'pending' AND created_at > '2024-01-01'
-- Does NOT work for: WHERE created_at > '2024-01-01' (leftmost prefix rule)
```
Reference: [Multicolumn Indexes](https://www.postgresql.org/docs/current/indexes-multicolumn.html)

---
title: Use Covering Indexes to Avoid Table Lookups
impact: MEDIUM-HIGH
impactDescription: 2-5x faster queries by eliminating heap fetches
tags: indexes, covering-index, include, index-only-scan
---
## Use Covering Indexes to Avoid Table Lookups
Covering indexes include all columns needed by a query, enabling index-only scans that skip the table entirely.
**Incorrect (index scan + heap fetch):**
```sql
create index users_email_idx on users (email);
-- Must fetch name and created_at from table heap
select email, name, created_at from users where email = 'user@example.com';
```
**Correct (index-only scan with INCLUDE):**
```sql
-- Include non-searchable columns in the index
create index users_email_idx on users (email) include (name, created_at);
-- All columns served from index, no table access needed
select email, name, created_at from users where email = 'user@example.com';
```
Use INCLUDE for columns you SELECT but don't filter on:
```sql
-- Searching by status, but also need customer_id and total
create index orders_status_idx on orders (status) include (customer_id, total);
select status, customer_id, total from orders where status = 'shipped';
```
Reference: [Index-Only Scans](https://www.postgresql.org/docs/current/indexes-index-only-scans.html)

---
title: Choose the Right Index Type for Your Data
impact: HIGH
impactDescription: 10-100x improvement with correct index type
tags: indexes, btree, gin, gist, brin, hash, index-types
---
## Choose the Right Index Type for Your Data
Different index types excel at different query patterns. The default B-tree isn't always optimal.
**Incorrect (B-tree for JSONB containment):**
```sql
-- B-tree cannot optimize containment operators
create index products_attrs_idx on products (attributes);
select * from products where attributes @> '{"color": "red"}';
-- Full table scan - B-tree doesn't support @> operator
```
**Correct (GIN for JSONB):**
```sql
-- GIN supports @>, ?, ?&, ?| operators
create index products_attrs_idx on products using gin (attributes);
select * from products where attributes @> '{"color": "red"}';
```
Index type guide:
```sql
-- B-tree (default): =, <, >, BETWEEN, IN, IS NULL
create index users_created_idx on users (created_at);
-- GIN: arrays, JSONB, full-text search
create index posts_tags_idx on posts using gin (tags);
-- GiST: geometric data, range types, nearest-neighbor (KNN) queries
create index locations_idx on places using gist (location);
-- BRIN: large time-series tables (10-100x smaller)
create index events_time_idx on events using brin (created_at);
-- Hash: equality-only (slightly faster than B-tree for =)
create index sessions_token_idx on sessions using hash (token);
```
Reference: [Index Types](https://www.postgresql.org/docs/current/indexes-types.html)

---
title: Add Indexes on WHERE and JOIN Columns
impact: CRITICAL
impactDescription: 100-1000x faster queries on large tables
tags: indexes, performance, sequential-scan, query-optimization
---
## Add Indexes on WHERE and JOIN Columns
Queries filtering or joining on unindexed columns cause full table scans, which become exponentially slower as tables grow.
**Incorrect (sequential scan on large table):**
```sql
-- No index on customer_id causes full table scan
select * from orders where customer_id = 123;
-- EXPLAIN shows: Seq Scan on orders (cost=0.00..25000.00 rows=100 width=85)
```
**Correct (index scan):**
```sql
-- Create index on frequently filtered column
create index orders_customer_id_idx on orders (customer_id);
select * from orders where customer_id = 123;
-- EXPLAIN shows: Index Scan using orders_customer_id_idx (cost=0.42..8.44 rows=100 width=85)
```
For JOIN columns, always index the foreign key side:
```sql
-- Index the referencing column
create index orders_customer_id_idx on orders (customer_id);
select c.name, o.total
from customers c
join orders o on o.customer_id = c.id;
```
Reference: [Query Optimization](https://supabase.com/docs/guides/database/query-optimization)

---
title: Use Partial Indexes for Filtered Queries
impact: HIGH
impactDescription: 5-20x smaller indexes, faster writes and queries
tags: indexes, partial-index, query-optimization, storage
---
## Use Partial Indexes for Filtered Queries
Partial indexes only include rows matching a WHERE condition, making them smaller and faster when queries consistently filter on the same condition.
**Incorrect (full index includes irrelevant rows):**
```sql
-- Index includes all rows, even soft-deleted ones
create index users_email_idx on users (email);
-- Query always filters active users
select * from users where email = 'user@example.com' and deleted_at is null;
```
**Correct (partial index matches query filter):**
```sql
-- Index only includes active users
create index users_active_email_idx on users (email)
where deleted_at is null;
-- Query uses the smaller, faster index
select * from users where email = 'user@example.com' and deleted_at is null;
```
Common use cases for partial indexes:
```sql
-- Only pending orders (status rarely changes once completed)
create index orders_pending_idx on orders (created_at)
where status = 'pending';
-- Only non-null values
create index products_sku_idx on products (sku)
where sku is not null;
```
Reference: [Partial Indexes](https://www.postgresql.org/docs/current/indexes-partial.html)
