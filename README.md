# Token Saver CLI v9.0

Reduce token waste and spending when using AI coding models. Compare pricing across **all providers**, compress file reads and shell output, cache re-reads, run a request compression proxy, and track savings with a tamper-evident ledger. Now with **SQLite FTS5 search**, **MCP server**, and **agent skill installer**.

**Inspired by [lean-ctx](https://github.com/yvgude/lean-ctx)** and [ctxrs/ctx](https://github.com/ctxrs/ctx) — context engineering + agent history search.

## Features

### Provider & Model Management (v1-7)
- **Provider-agnostic model switching** — pick any model from any configured provider
- **Quick-set tiers** — `set cheapest`, `set cheap`, `set balanced`, `set strong`
- **Task-based recommendations** — model suggestions for coding, review, planning
- **Pricing heatmap** — cheapest model per capability (tools, 128k+ ctx, reasoning)
- **Provider health check** — ping each configured provider for connectivity
- **Cost projection** — estimate session costs across light/medium/heavy usage
- **Compaction toggle** — enables auto + prune + reserved for 30-50% savings
- **Free model browser** — shows free models from your providers
- **New model detection** — auto-detects newly added models from models.dev

### Compression Engine (v8 — lean-ctx inspired)

#### File Read Compression
- **8 read modes**: `full`, `map`, `signatures`, `density:X`, `diff`, `lines:N-M`, `stats`, `semantic`
- `map` — extracts imports, classes, functions, constants (~98% compression on code files)
- `signatures` — function/class signatures with line spans (~97% compression)
- `density:X` — keeps highest-entropy lines until X% token budget remains
- `diff` — shows only git-changed lines vs a ref
- `stats` — file metadata only (99%+ compression)
- `semantic` — AI summarization using your configured small model (falls back to map mode if unavailable)

#### Shell Output Compression
- **16+ command patterns**: `git status`, `git diff`, `git log`, `git branch`, `npm test`, `npm install`, `cargo build`, `cargo test`, `docker ps`, `docker images`, `kubectl get`, `pip list`, `ls`, `ps`, `find`, `terraform plan`
- **Generic compression**: deduplicates repeated lines, truncates long output, adds line summaries
- Typical savings: 60-95% on git/npm/cargo/docker output

#### Content Cache
- **Content-addressable cache**: SHA256-keyed, TTL-based (1 hour)
- **Cached re-reads cost ~13 tokens**: instead of full file content
- **Auto-caching**: file reads are cached on first access

#### Request Compression Proxy
- **Local HTTP proxy** that compresses API requests before they reach the model
- **Cost-aware compression**: aggressively compresses requests for expensive models (>$20/M), moderate for mid-range, minimal for cheap/free models
- Compresses message content (system prompts, user messages, tool results)
- Tracks per-request savings in real-time
- Port: 8199 (configurable)

#### Content-Addressed Store
- **SHA256-based content addressing** for reversible compression
- Store original content → get a deterministic hash
- Retrieve original bytes by hash at any time

#### Token Budget Planner
- **Phi-scored allocation**: file_reads (35%), shell_commands (15%), reasoning (30%), output (20%)
- Track usage per category against budget
- Over-budget warnings

#### Savings Ledger
- **Tamper-evident**: SHA256 hash chain (each entry links to previous hash)
- **Self-verifying**: `savings verify` confirms ledger integrity
- Per-entry tracking of raw tokens, compressed tokens, compression %

### New in v9.0 (ctxrs/ctx inspired)

#### SQLite FTS5 Search Index
- **Full-text search** across compression history, proxy requests, and cache entries
- **SQL queries** for aggregate stats: `token-saver sql "SELECT kind, SUM(saved_tokens) FROM events GROUP BY kind"`
- **File touch tracking**: search which files were previously compressed
- Replaces 8+ JSON files with a single `index.db`

#### MCP Server (Model Context Protocol)
- **Agent integration**: expose compression tools to OpenCode, Claude Code, Cursor
- **7 tools**: `compress_file`, `compress_shell`, `search_savings`, `search_files`, `get_stats`, `get_config`, `sql_query`
- **Two transports**: stdio (CLI agents) or HTTP (IDE integration)

#### Agent Skill Installer
- **One-command install**: `token-saver skill install opencode|cursor|codex|claude`
- **Auto-discovery**: agents find and use Token Saver automatically
- **SKILL.md manifest**: documents compression modes, proxy, search, and workflows

#### Self-Upgrade
- **Version check**: `token-saver upgrade --check` compares against GitHub releases
- **Apply updates**: `token-saver upgrade --apply` downloads latest

## Requirements

- Python 3.8+
- `rich`, `click`, `requests` (`pip install rich click requests`)

## Installation

```bash
pip install rich click requests
python token-saver.py
```

## Usage

### Model & Provider Commands
```bash
python token-saver.py                              # Interactive menu
python token-saver.py set cheapest                 # Quick-set model tier
python token-saver.py save-max                     # One-command full optimization (cheapest models, compaction, fallbacks, proxy)
python token-saver.py save-max --no-proxy          # Same but skip the proxy
python token-saver.py save-money --mode free       # Prefer free models and preserve limited free-tier tokens
python token-saver.py save-money --mode paid --max-paid-cost 5 --apply  # Cap paid model spend and apply
python token-saver.py compare                      # Compare all providers
python token-saver.py compare --free --tools       # Free models with tool support
python token-saver.py health                       # Check provider connectivity
python token-saver.py providers                    # List providers & API key status
python token-saver.py verify                       # Verify settings are active
python token-saver.py restore --list               # List config backups
```

### Search & SQL Commands (New — ctxrs/ctx inspired)
```bash
python token-saver.py search "git status compression"          # Full-text search history
python token-saver.py search --file src/auth.py                 # Search by file
python token-saver.py search --kind file_read --since 7d       # Filter by kind + time
python token-saver.py sql "SELECT kind, SUM(saved_tokens) FROM events GROUP BY kind"
python token-saver.py sql "SELECT path, compression_pct FROM files_touched ORDER BY compression_pct DESC LIMIT 10"
python token-saver.py stats                                     # Aggregate statistics
```

### MCP Server & Agent Skills (New — ctxrs/ctx inspired)
```bash
python token-saver.py mcp start --transport stdio    # Start MCP server for CLI agents
python token-saver.py mcp start --transport http     # Start MCP server for IDE
python token-saver.py mcp status                     # Check MCP server status
python token-saver.py skill install opencode         # Install skill for OpenCode
python token-saver.py skill install cursor           # Install skill for Cursor
python token-saver.py skill status                   # Check installation status
```

### Self-Upgrade (New)
```bash
python token-saver.py upgrade --check    # Check for updates
python token-saver.py upgrade --apply    # Apply update
```

### Compression Commands (New)
```bash
# File Read Compression
python token-saver.py compress read main.py --mode map          # 98% compression
python token-saver.py compress read main.py --mode signatures   # 97% compression
python token-saver.py compress read main.py --mode density:0.3  # Keep 30% densest lines
python token-saver.py compress read main.py --mode lines:10-30  # Specific line range
python token-saver.py compress read main.py --mode stats        # File metadata only
python token-saver.py compress read main.py --mode diff --ref HEAD~1  # Git diff
python token-saver.py compress read main.py --no-cache          # Bypass cache
python token-saver.py compress read main.py --json              # JSON output

# Shell Output Compression
python token-saver.py compress shell "git status"               # Compressed git status
python token-saver.py compress shell "npm test"                 # Test output summary
python token-saver.py compress shell "docker ps"                # Container summary
python token-saver.py compress shell "cargo build"              # Build errors/warnings
python token-saver.py compress shell "git log --oneline -10" --json

# Test Messages Compression
python token-saver.py compress messages                          # Sample API request compression

# Batch Compression (NEW)
python token-saver.py compress batch src/ --mode map            # Compress entire directory
python token-saver.py compress batch src/ -r --ext .py,.js      # Recursive with extension filter
python token-saver.py compress batch src/ --json                 # JSON output

# Semantic Compression (NEW — AI summarization)
python token-saver.py compress semantic main.py                 # Summarize file with LLM
python token-saver.py compress semantic main.py --max-tokens 500
python token-saver.py compress semantic main.py --json
```

### Practical Money Saver
```bash
# Preview recommended setup without changing config
python token-saver.py save-money --mode free
python token-saver.py save-money --mode paid --max-paid-cost 5

# Apply the setup to OpenCode config
python token-saver.py save-money --mode free --apply
python token-saver.py save-money --mode paid --max-paid-cost 3 --daily-budget 1 --apply
python token-saver.py save-money --mode paid --provider openai --apply

# Skip proxy if you only want model + fallback changes
python token-saver.py save-money --mode paid --apply --no-proxy
```

`free` mode prefers configured free models first and stores a soft free-tier token limit.
`paid` mode caps paid candidates by input+output price per million tokens, sets a cheaper small model, enables compaction, and creates fallback chains away from expensive models.

### Cache Management
```bash
python token-saver.py cache stats     # Show cache statistics
python token-saver.py cache list      # List cached files
python token-saver.py cache clear     # Clear all cached reads
```

### Request Compression Proxy
```bash
python token-saver.py proxy start --port 8199   # Start the compression proxy
python token-saver.py proxy stop                 # Stop the proxy
python token-saver.py proxy status               # Show proxy status

# Generic IDE/CLI mode: do not edit OpenCode config
python token-saver.py proxy start --generic --provider openai
python token-saver.py proxy env --provider openai
```

For VS Code extensions, Hermes, custom scripts, or any OpenAI-compatible CLI, set the client base URL to:

```text
http://127.0.0.1:8199/v1
```

Keep using the normal provider API key. The tool compresses requests before forwarding them upstream. Automatic config writing is OpenCode-specific; generic mode is portable to any client that lets you set an OpenAI-compatible API base URL.

### Token Budget Planner
```bash
python token-saver.py budget plan "refactor auth module" --limit 8000
python token-saver.py budget track 3500 --kind file_reads
```

### Savings Ledger
```bash
python token-saver.py savings summary     # Show total savings
python token-saver.py savings verify      # Verify ledger integrity (hash chain)
python token-saver.py savings ledger      # Show recent entries
```

### Content-Addressed Store
```bash
python token-saver.py store put "some content to store"
python token-saver.py store get <hash_id>
```

### Fallback Chains (NEW)
```bash
python token-saver.py fallback set "openai/gpt-4" "openai/gpt-4o-mini" "anthropic/claude-3-haiku"
python token-saver.py fallback list
python token-saver.py fallback resolve "openai/gpt-4"
python token-saver.py fallback remove "openai/gpt-4"
```

### Web Dashboard (NEW)
```bash
python token-saver.py dashboard start --port 8200    # Start dashboard
python token-saver.py dashboard status                # Check status
python token-saver.py dashboard stop                  # Stop dashboard
```
Open http://127.0.0.1:8200 in your browser for real-time monitoring of cache stats, savings, proxy, budget, store, and fallback chains.

## Interactive Menu

Run without subcommand to see the full interactive menu:

```
  +============================================+
  | OpenCode Token Saver CLI v8.0              |
  | Compare · Compress · Cache · Proxy          |
  +============================================+

  Current Status
    Model    : gpt-4o
    Small    : gpt-4o-mini
    Compact  : auto=ON  prune=ON  reserved=10000

  -- Menu --

  1. Practical Saver (save-money)
  2. Switch Main Model
  3. Switch Small Model
  4. Compare Models & Costs
  5. Cost Projection
   -- TOKEN REDUCTION --
  6. Compress File
  7. Compress Shell Output
  8. Cache Stats / Clear Cache
   -- GUARDRAILS --
  9. Compression Proxy
  10. Token Budget
  11. Savings Report
   -- SETTINGS --
  12. Providers & API Status
  13. Provider Health Check
  14. Verify Config
  15. Restore Backup
  16. Exit
```

## Compression Benchmarks

| Read Mode | Compression | Typical Savings |
| `semantic` | 90-99%     | AI summarization via small model (falls back to map) |
|-----------|-------------|-----------------|
| `stats`   | 99.8%       | File metadata only |
| `map`     | 95-98%      | Only symbols (imports, classes, functions) |
| `signatures` | 94-97%   | Function/class signatures with line refs |
| `density:0.4` | 55-65% | Highest-entropy lines only |
| `lines:N-M` | variable  | Specific line range |
| `diff`    | variable    | Only changed lines |

| Shell Command | Compression | Typical Savings |
|---------------|-------------|-----------------|
| `git status`  | 90-95%      | Compact branch + file counts |
| `git diff`    | 85-95%      | File list + +/- stats |
| `git log`     | 80-90%      | Truncated to 20 entries |
| `npm test`    | 70-85%      | Failures + summary only |
| `cargo build` | 60-80%      | Errors + warnings only |
| `docker ps`   | 80-90%      | Container count + status |

## Configuration

The tool reads and writes to:
- **Config**: `~/.config/opencode/opencode.jsonc`
- **Backups**: `~/.config/opencode/opencode.jsonc.{timestamp}.backup` (last 5)
- **Cache**: `~/.config/opencode/models_cache.json` (24h TTL)
- **Compression**: `~/.config/opencode/compress/` (cache, store, ledger, budget, proxy config)

## Data Source

Model pricing fetched live from [models.dev/api.json](https://models.dev/api.json). Cached locally for 24 hours.
