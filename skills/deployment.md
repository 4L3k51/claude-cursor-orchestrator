# Deployment Phase - Supabase Guidance
<!--
  Build phase: deployment
  This file is injected during deployment steps.
  Populate with guidance for: hosting platform deployment, environment variables,
  Edge Function deployment, production configuration, CI/CD patterns.
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
title: Use EXPLAIN ANALYZE to Diagnose Slow Queries
impact: LOW-MEDIUM
impactDescription: Identify exact bottlenecks in query execution
tags: explain, analyze, diagnostics, query-plan
---
## Use EXPLAIN ANALYZE to Diagnose Slow Queries
EXPLAIN ANALYZE executes the query and shows actual timings, revealing the true performance bottlenecks.
**Incorrect (guessing at performance issues):**
```sql
-- Query is slow, but why?
select * from orders where customer_id = 123 and status = 'pending';
-- "It must be missing an index" - but which one?
```
**Correct (use EXPLAIN ANALYZE):**
```sql
explain (analyze, buffers, format text)
select * from orders where customer_id = 123 and status = 'pending';
-- Output reveals the issue:
-- Seq Scan on orders (cost=0.00..25000.00 rows=50 width=100) (actual time=0.015..450.123 rows=50 loops=1)
--   Filter: ((customer_id = 123) AND (status = 'pending'::text))
--   Rows Removed by Filter: 999950
--   Buffers: shared hit=5000 read=15000
-- Planning Time: 0.150 ms
-- Execution Time: 450.500 ms
```
Key things to look for:
```sql
-- Seq Scan on large tables = missing index
-- Rows Removed by Filter = poor selectivity or missing index
-- Buffers: read >> hit = data not cached, needs more memory
-- Nested Loop with high loops = consider different join strategy
-- Sort Method: external merge = work_mem too low
```
Reference: [EXPLAIN](https://supabase.com/docs/guides/database/inspect)

---
title: Enable pg_stat_statements for Query Analysis
impact: LOW-MEDIUM
impactDescription: Identify top resource-consuming queries
tags: pg-stat-statements, monitoring, statistics, performance
---
## Enable pg_stat_statements for Query Analysis
pg_stat_statements tracks execution statistics for all queries, helping identify slow and frequent queries.
**Incorrect (no visibility into query patterns):**
```sql
-- Database is slow, but which queries are the problem?
-- No way to know without pg_stat_statements
```
**Correct (enable and query pg_stat_statements):**
```sql
-- Enable the extension
create extension if not exists pg_stat_statements;
-- Find slowest queries by total time
select
  calls,
  round(total_exec_time::numeric, 2) as total_time_ms,
  round(mean_exec_time::numeric, 2) as mean_time_ms,
  query
from pg_stat_statements
order by total_exec_time desc
limit 10;
-- Find most frequent queries
select calls, query
from pg_stat_statements
order by calls desc
limit 10;
-- Reset statistics after optimization
select pg_stat_statements_reset();
```
Key metrics to monitor:
```sql
-- Queries with high mean time (candidates for optimization)
select query, mean_exec_time, calls
from pg_stat_statements
where mean_exec_time > 100  -- > 100ms average
order by mean_exec_time desc;
```
Reference: [pg_stat_statements](https://supabase.com/docs/guides/database/extensions/pg_stat_statements)

---
title: Maintain Table Statistics with VACUUM and ANALYZE
impact: MEDIUM
impactDescription: 2-10x better query plans with accurate statistics
tags: vacuum, analyze, statistics, maintenance, autovacuum
---
## Maintain Table Statistics with VACUUM and ANALYZE
Outdated statistics cause the query planner to make poor decisions. VACUUM reclaims space, ANALYZE updates statistics.
**Incorrect (stale statistics):**
```sql
-- Table has 1M rows but stats say 1000
-- Query planner chooses wrong strategy
explain select * from orders where status = 'pending';
-- Shows: Seq Scan (because stats show small table)
-- Actually: Index Scan would be much faster
```
**Correct (maintain fresh statistics):**
```sql
-- Manually analyze after large data changes
analyze orders;
-- Analyze specific columns used in WHERE clauses
analyze orders (status, created_at);
-- Check when tables were last analyzed
select
  relname,
  last_vacuum,
  last_autovacuum,
  last_analyze,
  last_autoanalyze
from pg_stat_user_tables
order by last_analyze nulls first;
```
Autovacuum tuning for busy tables:
```sql
-- Increase frequency for high-churn tables
alter table orders set (
  autovacuum_vacuum_scale_factor = 0.05,     -- Vacuum at 5% dead tuples (default 20%)
  autovacuum_analyze_scale_factor = 0.02     -- Analyze at 2% changes (default 10%)
);
-- Check autovacuum status
select * from pg_stat_progress_vacuum;
```
Reference: [VACUUM](https://supabase.com/docs/guides/database/database-size#vacuum-operations)
