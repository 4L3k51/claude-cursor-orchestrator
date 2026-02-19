# Setup Phase - Supabase Guidance
<!--
  Build phase: setup
  This file is injected during project initialization steps.
  Populate with guidance for: project scaffolding, dependency installation,
  Supabase CLI setup, environment configuration, Playwright installation.
-->

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
