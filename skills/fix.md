# Fix Phase - Supabase Guidance
<!--
  Build phase: fix
  This file is injected during smoke test fix steps.
  Populate with guidance for: common error patterns, debugging strategies,
  Supabase-specific error codes, recovery procedures.
-->

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
title: Prevent Deadlocks with Consistent Lock Ordering
impact: MEDIUM-HIGH
impactDescription: Eliminate deadlock errors, improve reliability
tags: deadlocks, locking, transactions, ordering
---
## Prevent Deadlocks with Consistent Lock Ordering
Deadlocks occur when transactions lock resources in different orders. Always
acquire locks in a consistent order.
**Incorrect (inconsistent lock ordering):**
```sql
-- Transaction A                    -- Transaction B
begin;                              begin;
update accounts                     update accounts
set balance = balance - 100         set balance = balance - 50
where id = 1;                       where id = 2;  -- B locks row 2
update accounts                     update accounts
set balance = balance + 100         set balance = balance + 50
where id = 2;  -- A waits for B     where id = 1;  -- B waits for A
-- DEADLOCK! Both waiting for each other
```
**Correct (lock rows in consistent order first):**
```sql
-- Explicitly acquire locks in ID order before updating
begin;
select * from accounts where id in (1, 2) order by id for update;
-- Now perform updates in any order - locks already held
update accounts set balance = balance - 100 where id = 1;
update accounts set balance = balance + 100 where id = 2;
commit;
```
Alternative: use a single statement to update atomically:
```sql
-- Single statement acquires all locks atomically
begin;
update accounts
set balance = balance + case id
  when 1 then -100
  when 2 then 100
end
where id in (1, 2);
commit;
```
Detect deadlocks in logs:
```sql
-- Check for recent deadlocks
select * from pg_stat_database where deadlocks > 0;
-- Enable deadlock logging
set log_lock_waits = on;
set deadlock_timeout = '1s';
```
Reference:
[Deadlocks](https://www.postgresql.org/docs/current/explicit-locking.html#LOCKING-DEADLOCKS)

---
title: Keep Transactions Short to Reduce Lock Contention
impact: MEDIUM-HIGH
impactDescription: 3-5x throughput improvement, fewer deadlocks
tags: transactions, locking, contention, performance
---
## Keep Transactions Short to Reduce Lock Contention
Long-running transactions hold locks that block other queries. Keep transactions as short as possible.
**Incorrect (long transaction with external calls):**
```sql
begin;
select * from orders where id = 1 for update;  -- Lock acquired
-- Application makes HTTP call to payment API (2-5 seconds)
-- Other queries on this row are blocked!
update orders set status = 'paid' where id = 1;
commit;  -- Lock held for entire duration
```
**Correct (minimal transaction scope):**
```sql
-- Validate data and call APIs outside transaction
-- Application: response = await paymentAPI.charge(...)
-- Only hold lock for the actual update
begin;
update orders
set status = 'paid', payment_id = $1
where id = $2 and status = 'pending'
returning *;
commit;  -- Lock held for milliseconds
```
Use `statement_timeout` to prevent runaway transactions:
```sql
-- Abort queries running longer than 30 seconds
set statement_timeout = '30s';
-- Or per-session
set local statement_timeout = '5s';
```
Reference: [Transaction Management](https://www.postgresql.org/docs/current/tutorial-transactions.html)

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
