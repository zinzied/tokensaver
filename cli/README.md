# ██▄▄ ██▓ ▒█████ ▒█████ ▓█████▄▓██ ██▓
# ▓█████▄ ▓██▒ ▒██▒ ██▒▒██▒ ██▒▒██▀ ██▌▒██ ██▒
# ▒██▒ ▄██▒██░ ▒██░ ██▒▒██░ ██▒░██ █▌ ▒██ ██░
# ▒██░█▀ ▒██░ ▒██ ██░▒██ ██░░▓█▄ ▌ ░ ▐██▓░
# ░▓█ ▀█▓░██████▒░ ████▓▒░░ ████▓▒░░▒████▓ ░ ██▒▓░
# ░▒▓███▀▒░ ▒░▓ ░░ ▒░▒░▒░ ░ ▒░▒░▒░ ▒▒▓ ▒ ██▒▒▒
# ▒░▒ ░ ░ ░ ▒ ░ ░ ▒ ▒░ ░ ▒ ▒░ ░ ▒ ▒ ▓██ ░▒░
# ░ ░ ░ ░ ░ ░ ▒ ░ ░ ░ ▒ ░ ░ ░ ▒ ▒ ░░
# ░ ░ ░ ░ ░ ░ ░ ░ ░ ░  

Reduce token waste and spending when using AI coding models. Compare pricing across **all providers**, compress requests and tool output, route through a local proxy, and track savings — all from a reactive TUI or the command line.

**Inspired by [lean-ctx](https://github.com/yvgude/lean-ctx)** and [ctxrs/ctx](https://github.com/ctxrs/ctx) — context engineering + agent history search. Advanced features (RTK compression, caveman mode, format translation, quota tracking, multi-account routing) draw on proven ideas from the open-source routing gateway ecosystem.

## Features

### Compression Engine

#### RTK Tool-Result Compression
13 smart filters that auto-detect and compress tool output before sending to the LLM:

| Filter | Compression | Description |
|--------|-------------|-------------|
| `git diff` | 40-60% | File headers, hunk truncation, +/- summaries |
| `git status` | 40-70% | Branch + file counts with caps |
| `git log` | 60-80% | Commit subjects only, drop bodies |
| `grep` results | 50-70% | Group by file, cap matches per file |
| `find` results | 50-70% | Group by directory, cap entries |
| `ls -la` | 30-50% | Compact listing + extension summary |
| `tree` | 10-30% | Drop summary line, cap depth |
| build logs | 60-80% | Errors + warnings + summary only |
| duplicate lines | 20-40% | Collapse consecutive repeats |
| `tool-result-prune` | 50-80% | Head/tail pruning for oversized output |

Auto-detects the right filter — no manual selector needed. Safe: falls back to raw text if compression would lose data.

#### Tool-Result Head/Tail Pruning
When tool output exceeds 8192 characters, keeps the first 4096 chars + `[... tool result middle pruned ...]` + last 1024 chars. Model-free (no LLM call needed) — just character slicing.

#### Caveman / Ponytail Mode
- **Caveman Mode** — terse-output system prompts (6 levels: lite → ultra, including Wenyan classical Chinese)
- **Ponytail Mode** — "lazy senior dev" persona: biases toward stdlib, native features, minimal code
- Up to **65% output token savings** with aggressive levels
- Format-aware injection: works with OpenAI, Claude, and Gemini request formats

#### Compaction Checkpoint Format
Structured Markdown checkpoint for conversation summarization:
- Primary Request, Key Technical Concepts, Files/Code, Errors/Fixes, Pending Jobs, Current Work, Next Step, Critical Context
- Reuses the conversation's own system prompt for KV-cache alignment

#### Token Estimation Heuristics
Heuristic token pricing without actual tokenization:
- `CHARS_PER_TOKEN = 4` for text
- `BLOCK_OVERHEAD = 4` for content blocks
- `ROLE_OVERHEAD = 4` for message framing
- Estimates cost per-message, per-content-block, per-request

### Request Compression Proxy

Local HTTP proxy that compresses API requests before they reach the model:

- **Cost-aware compression**: aggressively compresses requests for expensive models, moderate for mid-range, minimal for cheap/free
- **Auto-proxy all providers**: detects configured providers and adds them to the proxy automatically
- **Bare model routing**: maps bare model IDs to their real provider via catalog
- **Provider prefix stripping**: strips `opencode/big-pickle` → `big-pickle` before forwarding
- **Retry with exponential backoff + jitter**: configurable `maxRetries`, `initialDelayMs`, `maxDelayMs`, `jitterRatio`, `retryableCodes`
- Tracks per-request savings in real-time
- Port: 8199 (configurable)

### Todo & Goal Tracking

#### Todo Items
Persistent task tracker with status lifecycle:
- `pending` → `done` or `cancelled`
- Stored in `~/.config/opencode/todo.json`
- CLI: `todo add|list|done|cancel|remove|clear`
- TUI page with pending/done/cancelled sections

#### Goals
Session-level objectives with lifecycle:
- `active` → `completed` or `abandoned`
- Stored in `~/.config/opencode/goals.json`
- CLI: `goal add|list|done|abandon|remove|clear`
- TUI page with active/completed/abandoned sections

### Scheduled Reminders

Session-local timers that trigger follow-ups:
- Add reminders with text and due time
- Check for due reminders
- Stored in `~/.config/opencode/reminders.json`
- CLI: `remind add <minutes> <text>|list|due|remove|clear`

### Claude Code / Codex Hook Bridges

Reads hook configurations from external tools and translates them to a common format:
- Reads `.claude/hooks.json` (Claude Code) or `hooks.json` (Codex)
- Matches tool names against matcher patterns (literal, pipe alternation, wildcard)
- Runs shell commands with configurable timeouts
- Returns exit codes, stdout, stderr, and duration

### Spill Policy

Persists oversized tool output to disk:
- When tool output exceeds 16KB, saves to `~/.config/opencode/spill/`
- Replaces inline result with bounded preview (head + tail)
- Auto-cleans spills older than 24 hours

### Loop-Hygiene Guards

Detects unproductive agent patterns:
- **Repeat-call detection**: warns when the same tool is called 3+ times in sequence
- **Per-window call limits**: caps total tool calls per time window
- Configurable thresholds: `repeatThreshold`, `windowMs`, `maxCallsPerWindow`

### Provider & Model Management

- **Provider-agnostic model switching** — pick any model from any configured provider
- **Quick-set tiers** — `set cheapest`, `set cheap`, `set balanced`, `set strong`
- **Task-based recommendations** — model suggestions for coding, review, planning
- **Pricing heatmap** — cheapest model per capability (tools, 128k+ ctx, reasoning)
- **Provider health check** — ping each configured provider for connectivity
- **Cost projection** — estimate session costs across light/medium/heavy usage
- **Auto-proxy all providers** — detects 30+ providers and adds them to the proxy

### Format Translation

- **OpenAI ↔ Claude format conversion** for both requests and streaming responses
- Registry-based translator pattern (extensible to Gemini, Kiro, Cursor, Ollama)
- Handles tool calls, image data, system messages, and content blocks

### 3-Tier Fallback Routing

- **Provider tiers**: Subscription → Cheap → Free
- **Smart error classification**: HTTP 429/401/403/503 trigger exponential backoff
- **Auto-fallback**: when a provider hits rate limits or quota, the router tries the next tier

### Multi-Account Round-Robin

- **Multiple API keys per provider** with priority-based selection
- **Round-robin rotation** across accounts to maximize free-tier quota
- **Exponential backoff** on errors (2s → 4s → 8s → ... → 5 min max)
- **Model-level locks**: prevent a model from hitting the same account repeatedly

### Quota Tracking

- **Per-provider quota**: remaining, total, reset countdown
- **Cost tracking**: cumulative spend per provider
- **Rate-limit detection**: automatic cooldown marking
- **Persistence**: data stored in `~/.config/opencode/compress/quota_tracker.json`

### SQLite FTS5 Search Index

- **Full-text search** across compression history, proxy requests, and cache entries
- **SQL queries** for aggregate stats
- **File touch tracking**: search which files were previously compressed

### MCP Server (Model Context Protocol)

- **Agent integration**: expose compression tools to OpenCode, Claude Code, Cursor
- **7 tools**: `compress_file`, `compress_shell`, `search_savings`, `search_files`, `get_stats`, `get_config`, `sql_query`
- **Two transports**: stdio (CLI agents) or HTTP (IDE integration)

## Architecture

```
bloody/
├── src/
│   ├── banner.ts          # ASCII art + APP_NAME
│   ├── index.tsx          # Entry point (TUI or CLI)
│   ├── cli/
│   │   └── commands.ts    # All CLI command handlers
│   ├── core/
│   │   ├── config.ts      # Config read/write, provider detection
│   │   ├── models.ts      # Model catalog, pricing, recommendations
│   │   ├── proxy.ts       # Compression proxy with auto-routing
│   │   ├── routing.ts     # 3-tier fallback, account rotation
│   │   ├── quota.ts       # Quota tracking, rate limits
│   │   ├── insights.ts    # Summary data for TUI pages
│   │   ├── prompts.ts     # Caveman/Ponytail/compaction prompts
│   │   ├── translate.ts   # Format translation (OpenAI↔Claude)
│   │   ├── utils.ts       # Shared utilities
│   │   ├── types.ts       # TypeScript interfaces
│   │   ├── tokens.ts      # Token estimation heuristics
│   │   ├── todo.ts        # Todo tracking store
│   │   ├── goals.ts       # Goal persistence store
│   │   ├── reminders.ts   # Scheduled reminders store
│   │   ├── hooks.ts       # Claude Code/Codex hook bridges
│   │   ├── retry.ts       # Exponential backoff + jitter
│   │   ├── spill.ts       # Oversized output to disk
│   │   ├── guard.ts       # Loop-hygiene guards
│   │   └── filters/
│   │       └── rtk.ts     # 13 RTK compression filters
│   └── tui/
│       ├── App.tsx         # Shell with sidebar navigation
│       ├── components.tsx  # Reusable UI components
│       ├── input.tsx       # Keyboard input handling
│       ├── useData.ts      # Data polling hook
│       └── pages/
│           ├── OverviewPage.tsx
│           ├── UsagePage.tsx
│           ├── QuotaPage.tsx
│           ├── CompressPage.tsx
│           ├── ProxyPage.tsx
│           ├── RoutingPage.tsx
│           ├── ProvidersPage.tsx
│           ├── ModelsPage.tsx
│           ├── SearchPage.tsx
│           ├── TodoPage.tsx
│           ├── GoalsPage.tsx
│           └── SettingsPage.tsx
└── tests/
    ├── proxy.test.ts       # 78 tests
    └── newfeatures.test.ts # 19 tests
```

## Requirements

- Node.js v22+
- npm 10+

## Installation

```bash
cd cli
npm install
```

## Usage

### TUI (Interactive)

```bash
npm start          # or npm run dev
```

Navigate with arrow keys, press `q` to quit. 12 pages: Overview, Usage, Quota, Compress, Proxy, Routing, Providers, Models, Search, Todo, Goals, Settings.

### CLI (Non-Interactive)

```bash
# Overview
npx tsx src/index.tsx overview
npx tsx src/index.tsx usage

# Compression
npx tsx src/index.tsx compress test "$(git diff)"
npx tsx src/index.tsx rtk auto "$(git log)"

# Proxy
npx tsx src/index.tsx proxy start --port 8199
npx tsx src/index.tsx proxy stop
npx tsx src/index.tsx proxy status
npx tsx src/index.tsx proxy proxify --port 8199

# Todo
npx tsx src/index.tsx todo add "Fix the auth bug"
npx tsx src/index.tsx todo list
npx tsx src/index.tsx todo done <id>

# Goals
npx tsx src/index.tsx goal add "Ship v2.0"
npx tsx src/index.tsx goal list
npx tsx src/index.tsx goal done <id>

# Reminders
npx tsx src/index.tsx remind add 30 "Check usage"
npx tsx src/index.tsx remind due

# Models
npx tsx src/index.tsx models list
npx tsx src/index.tsx models choose --mode free
npx tsx src/index.tsx models recommend --task coding
npx tsx src/index.tsx models heatmap

# Settings
npx tsx src/index.tsx settings get
npx tsx src/index.tsx settings save --model M --small-model S

# Translation
npx tsx src/index.tsx translate detect '{"messages":[{"role":"user","content":"hi"}]}'
npx tsx src/index.tsx caveman inject --level ultra '{"messages":[]}'
```

## Configuration

- **Config**: `~/.config/opencode/opencode.jsonc`
- **Backups**: `~/.config/opencode/opencode.jsonc.{timestamp}.backup` (last 5)
- **Cache**: `~/.config/opencode/models_cache.json` (24h TTL)
- **Compression**: `~/.config/opencode/compress/`
- **Todo**: `~/.config/opencode/todo.json`
- **Goals**: `~/.config/opencode/goals.json`
- **Reminders**: `~/.config/opencode/reminders.json`
- **Spill**: `~/.config/opencode/spill/`

Override config directory with `TOKENSAVER_HOME` environment variable.

## Development

```bash
npm run typecheck   # Type checking
npm test            # Run all 97 tests
npm run build       # Build for production
```

### Tech Stack

- **Runtime**: Node.js v22+ with ESM
- **TUI**: React 19 + Ink 7 (terminal UI framework)
- **Database**: better-sqlite3 (FTS5 search)
- **Language**: TypeScript 5.9+ (strict mode)
- **Testing**: Node.js test runner + tsx

## Data Source

Model pricing fetched live from [models.dev/api.json](https://models.dev/api.json). Cached locally for 24 hours.
