# Token Saver CLI v9.5

Reduce token waste and spending when using AI coding models. Compare pricing across **all providers**, compress file reads and shell output, cache re-reads, run a request compression proxy, and track savings with a tamper-evident ledger. Now with **FROST system-prompt freeze**, **SQLite FTS5 search**, **MCP server**, and **agent skill installer**.

**Inspired by [lean-ctx](https://github.com/yvgude/lean-ctx)** and [ctxrs/ctx](https://github.com/ctxrs/ctx) — context engineering + agent history search.  
**Advanced features** (RTK compression, caveman mode, format translation, quota tracking, multi-account routing) draw on proven ideas from the open-source routing gateway ecosystem.

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

#### FROST — System Prompt Freeze (NEW; opt-in safety gate)
- **The single biggest per-turn waste in every agent session**: the client re-sends the full system prompt (typically 5–15k tokens) on *every single request*.
- FROST is **disabled by default for correctness**. Standard chat-completions APIs are stateless between HTTP requests, so an upstream model cannot recover a prompt replaced by a marker.
- FROST never rewrites prompts unless both `enabled: true` and the explicit acknowledgement `allow_stateless_marker: true` are present in `proxy.json`. Use that opt-in only with a protocol that demonstrably preserves the earlier prompt outside the request body.
- When explicitly enabled, it still requires a byte-identical SHA256, an unshrunk conversation, and an unexpired refresh threshold.

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

### Advanced Token-Saving Features (v9.5)

#### RTK Tool-Result Compression (token_filters.py)
- **12 smart filters** that auto-detect and compress tool output before sending to the LLM
- Covers: `git diff`, `git status`, `git log`, `grep`, `find`, `ls`, `tree`, build logs, duplicate lines, and more
- **20-40% input token savings** on typical tool_result content
- Auto-detects the right filter — no manual selector needed
- Safe: falls back to raw text if compression would lose data

#### Caveman / Ponytail Mode (token_prompts.py)
- **Caveman Mode** — injects terse-output system prompts (6 levels: lite → ultra, including Wenyan classical Chinese)
- **Ponytail Mode** — "lazy senior dev" persona: biases toward stdlib, native features, minimal code
- **Up to 65% output token savings** with aggressive levels
- Format-aware injection: works with OpenAI, Claude, and Gemini request formats
- Persistence rules: stays active across turns, auto-clarity for security/irreversible actions

#### Format Translation (token_translate.py)
- **OpenAI ↔ Claude format conversion** for both requests and streaming responses
- Registry-based translator pattern (extensible to Gemini, Kiro, Cursor, Ollama)
- Handles tool calls, image data, system messages, and content blocks

#### 3-Tier Fallback Routing (token_routing.py)
- **Provider tiers**: Subscription → Cheap → Free
- **Smart error classification**: HTTP 429/401/403/503 trigger exponential backoff
- **Auto-fallback**: when a provider hits rate limits or quota, the router tries the next tier
- **Resolve command**: test whether an error should trigger fallback

#### Multi-Account Round-Robin (token_routing.py + token_usages.py)
- **Multiple API keys per provider** with priority-based selection
- **Round-robin rotation** across accounts to maximize free-tier quota
- **Exponential backoff** on errors (2s → 4s → 8s → ... → 5 min max)
- **Model-level locks**: prevent a model from hitting the same account repeatedly

#### Quota Tracking (token_usages.py)
- **Per-provider quota**: remaining, total, reset countdown
- **Cost tracking**: cumulative spend per provider
- **Rate-limit detection**: automatic cooldown marking
- **Persistence**: data stored in `~/.config/opencode/compress/quota_tracker.json`

#### Auto Token Refresh (token_refresh.py)
- **OAuth token expiry checking**: decodes JWT tokens and checks remaining time
- **Pre-emptive refresh**: triggers when token is within configurable buffer window
- **Supported providers**: Claude Code (300s buffer), Gemini CLI (120s), GitHub Copilot (60s)
- **Register & track**: log tokens for automatic refresh management

### New in v9.0 (ctxrs/ctx inspired) — Search, MCP, Skills, Upgrade

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
python token-saver.py save-max                     # One-command full optimization (cheapest models, compaction, fallbacks, proxy; FROST stays safe/off)
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

`free` mode prefers configured free models first and stores a soft free-tier token limit (e.g., 500K-1M tokens/month). This preserves your limited token quota for when you need it most.
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

### FROST — System Prompt Freeze (NEW)
```bash
python token-saver.py frost on                     # Configure FROST but keep rewriting safely disabled
python token-saver.py frost on --allow-stateless-marker  # Explicitly opt into protocol-specific marker mode
python token-saver.py frost on --allow-stateless-marker --refresh-after-tokens 30000   # Smaller safety window
python token-saver.py frost off                    # Disable
python token-saver.py frost status                 # Status + total tokens saved
python token-saver.py frost test "<system prompt>" '[{"role":"user","content":"hi"}]'  # Dry-run
python token-saver.py proxy start --no-frost       # Force FROST off for one proxy run
```
`save-max` leaves FROST safely disabled. Standard chat-completions APIs are stateless between requests, so marker mode is only available with the explicit `--allow-stateless-marker` acknowledgement and a provider protocol that preserves the earlier system prompt outside the request body.

For VS Code extensions, Hermes, custom scripts, or any OpenAI-compatible CLI, set the client base URL to:

```text
http://127.0.0.1:8199/v1
```

Keep using the normal provider API key. The tool compresses requests before forwarding them upstream. Automatic config writing is OpenCode-specific; generic mode is portable to any client that lets you set an OpenAI-compatible API base URL.

### Local Proxy Verification

Run the hermetic integration test to measure the exact request body received by a fake upstream:

```bash
python proxy_self_test.py
```

It uses no API key and makes no external requests. It verifies that a compressible request is reduced, that oversized conversations are left unchanged by the safety bypass, and that the FROST safety gate is present in the generated proxy. Provider billing still needs to be checked against that provider's own usage data.

Codex in VS Code uses the OpenAI Responses API. Start the proxy in generic OpenAI mode, then add this to the active Codex `config.toml` (global or trusted-project `.codex/config.toml`) and restart VS Code:

```toml
openai_base_url = "http://127.0.0.1:8199/v1"
```

After sending a Codex prompt, run `python token-saver.py proxy status`; the request count and the relevant model entry in **Model history** should increase.

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

### Advanced Token-Saving Commands (NEW — v9.5)

#### RTK Tool-Result Compression
```bash
python token-saver.py rtk test "$(git diff)"              # Test RTK on git diff output
python token-saver.py rtk test "$(git status)"            # Test RTK on git status
python token-saver.py rtk test "$(grep -r foo .)"        # Test RTK on grep output
python token-saver.py rtk test "$(ls -la)"                # Test RTK on ls output
python token-saver.py rtk auto "$(git log)"              # Auto-detect which filter matches
python token-saver.py rtk filters                         # List all 12 available filters
```

#### Caveman / Ponytail Mode
```bash
python token-saver.py caveman inject lite                 # Show the lite caveman prompt
python token-saver.py caveman inject full                 # Full caveman mode (~50% output savings)
python token-saver.py caveman inject ultra                # Ultra compression (~65%)
python token-saver.py caveman inject wenyan               # Classical Chinese compression
python token-saver.py caveman ponytail lite               # Lazy senior dev (lite)
python token-saver.py caveman ponytail ultra              # YAGNI extremist
```

#### Format Translation
```bash
python token-saver.py translate detect '{"messages":[{"role":"user","content":"hi"}]}'
# Detects: openai, claude, gemini, etc.
```

#### 3-Tier Fallback Routing
```bash
python token-saver.py routing providers                   # Show Subscription→Cheap→Free tiers
python token-saver.py routing chain claude-code           # Full fallback chain for a provider
python token-saver.py routing resolve 429 "rate limit"    # Test if error triggers fallback
```

#### Quota Tracking
```bash
python token-saver.py quota show                          # Show all provider quotas
python token-saver.py quota show openai                   # Show quota for specific provider
python token-saver.py quota update openai --remaining 4000 --reset-at "2026-07-27T00:00:00Z"
```

#### Multi-Account Round-Robin
```bash
python token-saver.py accounts add openai --api-key sk-... --priority 0
python token-saver.py accounts add openai --api-key sk-... --priority 1
python token-saver.py accounts list                       # List all configured accounts
```

#### Auto Token Refresh
```bash
python token-saver.py token-refresh providers             # Show auto-refresh supported providers
python token-saver.py token-refresh check eyJhbGci...     # Check JWT token expiry
python token-saver.py token-refresh register openai sk-... --refresh-token rtk-...
python token-saver.py token-refresh status                # Show registered tokens
```

### Web Dashboard
```bash
python token-saver.py dashboard start --port 8200    # Start dashboard
python token-saver.py dashboard status                # Check status
python token-saver.py dashboard stop                  # Stop dashboard
```
Open http://127.0.0.1:8200 in your browser for a comprehensive 9-page dashboard:

- **Overview** — Total savings (incl. FROST), cache stats, proxy status, quota tracking
- **Usage** — Provider request volume, tokens in/out, estimated savings
- **Quota** — Per-provider quota usage, reset countdowns, rate limit status
- **Translator** — Format translation debug tool (OpenAI ↔ Claude ↔ Gemini)
- **Routing** — 3-tier fallback chains with **one-click preset combos**:
  - `maximize-claude` — Use Claude Pro subscription fully ($25/mo)
  - `free-forever` — Zero cost with production-ready models ($0)
  - `always-on` — 24/7 coding with 5 layers of fallback ($30-220/mo)
  - `openclaw-free` — Free AI for WhatsApp, Telegram, Slack ($0)
- **Providers** — Configured providers, API key status, batch testing
- **Console Log** — Real-time proxy and translation logs
- **Chat** — Test chat against any configured provider
- **Settings** — Proxy config, routing preferences, database backup

**Cost Display**: All costs shown are **estimated savings** (what you would have paid with paid APIs), not actual billing. You pay $0 with free tiers.

## Interactive Menu

Run without subcommand to see the full interactive menu:

```
  +==================================================+
  |  OpenCode Token Saver CLI v9.5              |
  |  Compare - Compress - Cache - Proxy - Search     |
  |  RTK + Caveman + FROST + Routing + Quota        |
  +==================================================+

  Current Status
    Model    : MiMo V2 Pro Free
    Small    : Ring 2.6 1T Free
    Compact  : auto=ON  prune=ON  reserved=10000
    Save mode: free  max_paid=$5.0/M

  -- Menu --

     1. >>> ONE-CLICK AUTO SETUP <<<
     2. Practical Saver (save-money)
     -- COMPARE & PICK --
     3. Compare Models & Costs
     4. Switch Main Model
     5. Switch Small Model
     6. Model Heatmap
     7. Cost Projection
     -- COMPRESS --
     8. Compress File Read
     9. Compress Shell Output
     10. Compress Batch Directory
     11. Semantic AI Compress
     -- CACHE --
     12. Cache Stats / Clear
     13. Content Store
     14. Savings Ledger
     -- PROXY --
     15. Start Compression Proxy
     16. Stop Proxy
     17. Proxy Status
     18. FROST System Prompt Freeze
      -- ADVANCED TOOLS --
     19. RTK Tool-Result Compression
     20. Caveman Mode (terse output)
     21. Ponytail Mode (lazy dev)
     22. Format Translation (OpenAI↔Claude)
     23. 3-Tier Fallback Routing
     24. Quota Tracking
     25. Multi-Account Manager
     26. Auto Token Refresh
      -- EXTRAS --
     27. Providers & API Status
     28. Provider Health Check
     29. Token Budget Planner
     30. Verify Config
     31. Restore Backup
     32. Exit
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

| RTK Tool Result | Compression | Description |
|-----------------|-------------|-------------|
| `git diff`     | 40-60%      | File headers, hunk truncation, +/- summaries |
| `git status`   | 40-70%      | Branch + file counts with caps |
| `git log`      | 60-80%      | Commit subjects only, drop bodies |
| `grep` results | 50-70%      | Group by file, cap matches per file |
| `find` results | 50-70%      | Group by directory, cap entries |
| `ls -la`       | 30-50%      | Compact listing + extension summary |
| `tree`         | 10-30%      | Drop summary line, cap depth |
| build logs     | 60-80%      | Errors + warnings + summary only |
| duplicate lines | 20-40%     | Collapse consecutive repeats |

## Configuration

The tool reads and writes to:
- **Config**: `~/.config/opencode/opencode.jsonc`
- **Backups**: `~/.config/opencode/opencode.jsonc.{timestamp}.backup` (last 5)
- **Cache**: `~/.config/opencode/models_cache.json` (24h TTL)
- **Compression**: `~/.config/opencode/compress/` (cache, store, ledger, budget, proxy config, quota tracking, accounts, tokens)

## Data Source

Model pricing fetched live from [models.dev/api.json](https://models.dev/api.json). Cached locally for 24 hours.
