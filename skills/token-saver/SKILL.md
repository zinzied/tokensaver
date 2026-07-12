---
name: token-saver
description: Use token-saver to compress file reads, shell output, and API requests before sending to expensive models. Reduces token waste by 60-90%.
version: 9.0
---

# Token Saver Skill

Use token-saver whenever reading files, running shell commands, or sending
API requests to reduce token consumption and save money.

## Prerequisites

- Install: `pip install rich click requests`
- The CLI is at `python token-saver.py` or `token-saver` if installed globally.

## When To Use

- Before reading a large file (>200 lines): compress with `map` mode
- Before running git/npm/cargo/docker commands: compress output
- When checking which model is cheapest: use `compare` or `heatmap`
- When setting up cost optimization: use `save-money`
- When an API request is going to an expensive model: use the proxy

## File Compression Modes

| Mode | Command | Compression | When to use |
|------|---------|-------------|-------------|
| `map` | `compress read <file> --mode map` | ~98% | Default. Extracts imports, classes, functions |
| `signatures` | `compress read <file> --mode signatures` | ~97% | When you only need function signatures |
| `density:0.3` | `compress read <file> --mode density:0.3` | ~70% | Keep 30% densest lines |
| `diff` | `compress read <file> --mode diff --ref HEAD~1` | variable | Only changed lines |
| `stats` | `compress read <file> --mode stats` | ~99% | File metadata only |
| `semantic` | `compress read <file> --mode semantic` | ~95% | AI summarization via small model |

## Shell Compression

```bash
python token-saver.py compress shell "git status"
python token-saver.py compress shell "git diff"
python token-saver.py compress shell "npm test"
python token-saver.py compress shell "cargo build"
python token-saver.py compress shell "docker ps"
```

## Model Selection

```bash
# Quick set by tier
python token-saver.py set cheapest
python token-saver.py set cheap
python token-saver.py set balanced
python token-saver.py set strong

# Practical money saver
python token-saver.py save-money --mode free --apply
python token-saver.py save-money --mode paid --max-paid-cost 5 --apply

# Full optimization (cheapest models + compaction + proxy + fallbacks)
python token-saver.py save-max
```

## Compression Proxy

Start the proxy to automatically compress all API requests:

```bash
python token-saver.py proxy start --port 8199
python token-saver.py proxy status
python token-saver.py proxy stop
```

The proxy is cost-aware: aggressively compresses for expensive models (>$/M),
moderate for mid-range, minimal for cheap/free models.

## Search History

Search previous compression operations:

```bash
python token-saver.py search "git status"
python token-saver.py search --file src/auth.py
python token-saver.py search --kind file_read --since 7d
python token-saver.py sql "SELECT kind, SUM(saved_tokens) FROM events GROUP BY kind"
```

## Stats & Verification

```bash
python token-saver.py stats              # Full statistics
python token-saver.py savings summary     # Savings ledger
python token-saver.py savings verify      # Verify hash chain integrity
python token-saver.py cache stats         # Cache hit rates
python token-saver.py proxy status        # Proxy token savings
```

## Example Workflow

1. Set up optimization: `python token-saver.py save-money --mode free --apply`
2. Start proxy: `python token-saver.py proxy start`
3. Read files compressed: `python token-saver.py compress read src/main.py --mode map`
4. Run shell compressed: `python token-saver.py compress shell "git status"`
5. Check savings: `python token-saver.py savings summary`
6. Search history: `python token-saver.py search "compression"`

## MCP Server

For agent integration via Model Context Protocol:

```bash
python token_mcp.py --transport stdio    # For CLI agents
python token_mcp.py --transport http     # For IDE integration
```

Tools available: `compress_file`, `compress_shell`, `search_savings`,
`search_files`, `get_stats`, `get_config`, `sql_query`.
