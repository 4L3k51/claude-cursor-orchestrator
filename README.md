# Claude × Cursor Orchestrator

Observation framework that coordinates **Claude Code** (planner/verifier) and **Cursor Agent** (implementer) to build apps while logging every token, tool call, and web search to **Supabase**.

## How It Works

```
You: "Build a Supabase todo app with auth"
                    │
                    ▼
        ┌───────────────────────┐
        │  Python Orchestrator  │
        └───────┬───────┬───────┘
                │       │
      ┌─────────▼─┐   ┌─▼──────────┐
      │Claude Code │   │  Cursor    │
      │  Plans &   │──▶│  Agent     │
      │  Verifies  │◀──│ Implements │
      └─────────┬──┘   └──┬────────┘
                │          │
        ┌───────▼──────────▼───────┐
        │   Supabase (JSONB logs)  │
        │   Every event captured   │
        └──────────────────────────┘
```

**One prompt in → fully built project + complete observation dataset out.**

For each step, the orchestrator runs:

1. **Plan** — Claude Code generates a step-by-step implementation plan
2. **Implement** — Cursor Agent builds each step (`--force` auto-applies changes)
3. **Review** — Claude Code reads the actual project files and verifies Cursor's work is correct
4. **Retry or Proceed** — If Claude Code says FAIL → Cursor retries with the issues appended. If PASS → next step
5. **Log** — Every token, tool call, file write, bash command, web search, and error → Supabase

Claude Code acts as the reviewer of Cursor Agent's implementation at every step. If Cursor makes a mistake, Claude Code catches it and the orchestrator sends Cursor back with specific feedback until the step passes.

## What Gets Logged

Everything is stored as JSONB in Supabase, queryable with SQL:

- Tool calls (`shellToolCall`, `editToolCall`, `readToolCall`, `WebSearch`, `WebFetch`)
- File diffs (full before/after content for every edit)
- Bash output (stdout, stderr, exit codes, execution time)
- Claude Code's review verdicts (PASS/FAIL with reasoning)
- Token usage (input/output tokens, cache hits, model used)
- Errors and retries
- Timing per step, per phase, per API call

## Quick Start

### 1. Install CLIs

```bash
# Claude Code
npm install -g @anthropic-ai/claude-code

# Cursor Agent
curl https://cursor.com/install -fsSL | bash
agent login
```

### 2. Install Python dependencies

```bash
pip install python-dotenv supabase
```

### 3. Set up Supabase

- Create a project at [supabase.com](https://supabase.com)
- Run `migration.sql` in the SQL Editor
- Copy your project URL and **service_role** key

### 4. Configure environment

```bash
cp .env.example .env
# Edit .env with your Supabase credentials
```

### 5. Preflight check

```bash
python preflight.py
```

### 6. Run

```bash
# Simple test
python orchestrator.py "Create a simple Node.js hello world project"

# Real build
python orchestrator.py "Build a Supabase todo app with email auth, RLS policies per user, and a React frontend"
```

## Querying Logs

```sql
-- Run overview
SELECT * FROM orchestrator_run_summary;

-- All errors
SELECT * FROM orchestrator_errors;

-- Tool usage breakdown
SELECT * FROM orchestrator_tool_usage;

-- Claude Code's review verdicts
SELECT id, step_number, phase, tool, parsed_result, duration_seconds
FROM orchestrator_steps
WHERE tool = 'claude_code' AND phase = 'verify';

-- Web searches
SELECT id, step_id, event_data->'message'->'content' as content
FROM orchestrator_events
WHERE event_data->>'type' = 'assistant'
AND (event_data->'message'->'content')::text LIKE '%WebSearch%';

-- Bash commands from Cursor Agent
SELECT id, step_id,
  event_data->'tool_call'->'shellToolCall'->'args'->>'command' as command
FROM orchestrator_events
WHERE event_data->>'type' = 'tool_call'
AND (event_data->'tool_call')::text LIKE '%shellToolCall%';
```

## Files

| File | Purpose |
|------|---------|
| `orchestrator.py` | Main loop — plans, implements, verifies, retries |
| `storage.py` | Supabase storage layer |
| `analyzer.py` | Post-run analysis — errors, tool usage, timeline |
| `preflight.py` | Pre-run check — verifies CLIs and connections |
| `migration.sql` | Supabase schema — tables, indexes, views |

## Known Issues

- **Cursor Agent hanging**: The `-p` mode sometimes doesn't release the terminal. The orchestrator kills it after 2 minutes of idle time.
- **Verification is file-based**: Claude Code verifies by reading files, not by running the app. Runtime errors (like React version conflicts) aren't caught.
- **Context limits**: For complex multi-step builds, later steps may lack full context. The orchestrator passes a summary of completed steps.

## License

MIT
