#!/usr/bin/env python3
"""Token Saver MCP Server — inspired by ctxrs/ctx's MCP integration.

Exposes compression, search, and stats tools via Model Context Protocol
so agents (OpenCode, Claude Code, Cursor, Codex) can query Token Saver directly.
"""

import json
import sys
import os
from pathlib import Path

# Add parent dir to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from token_index import (
    init_db, search_events, search_files, sql_query, stats_summary,
    log_event, log_cache_hit, log_proxy_request,
)
from token_saver import (
    FileReadCompressor, ShellOutputCompressor, ContentCache,
    rough_token_count, read_config,
)

MCP_PORT = int(os.environ.get("TOKEN_SAVER_MCP_PORT", "8201"))
MCP_CONFIG = Path.home() / ".config" / "opencode" / "compress" / "mcp.json"

# ---------------------------------------------------------------------------
# Tool definitions (JSON Schema)
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "compress_file",
        "description": "Read and compress a file. Returns compressed content with token savings.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute file path"},
                "mode": {
                    "type": "string",
                    "enum": ["full", "map", "signatures", "density", "diff", "lines", "stats", "semantic"],
                    "default": "map",
                    "description": "Compression mode. map=98%%, signatures=97%%, density:X=keep X%% densest lines"
                },
                "density": {"type": "number", "description": "Density ratio (0.0-1.0) when mode=density"},
                "ref": {"type": "string", "description": "Git ref for diff mode (e.g. HEAD~1)"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "compress_shell",
        "description": "Run a shell command and compress its output. Handles git, npm, cargo, docker, etc.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to run"},
                "timeout": {"type": "integer", "default": 30, "description": "Timeout in seconds"},
            },
            "required": ["command"],
        },
    },
    {
        "name": "search_savings",
        "description": "Search compression history using full-text search.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query (natural language)"},
                "kind": {"type": "string", "description": "Filter by event kind: file_read, shell, proxy, cache_hit"},
                "since": {"type": "string", "description": "Time filter: 30d, 7d, 24h, 60m"},
                "limit": {"type": "integer", "default": 10, "description": "Max results"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_files",
        "description": "Search for files that were previously compressed.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "File path or name to search for"},
                "limit": {"type": "integer", "default": 10, "description": "Max results"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_stats",
        "description": "Get aggregate compression statistics: total savings, cache hits, proxy stats.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_config",
        "description": "Get current Token Saver configuration: model, small_model, compaction settings.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "sql_query",
        "description": "Execute a read-only SQL query against the compression index.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "SELECT SQL query"},
            },
            "required": ["query"],
        },
    },
]


# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------

def handle_tool(name: str, arguments: dict) -> dict:
    """Execute a tool and return the result."""
    try:
        if name == "compress_file":
            path = arguments["path"]
            mode = arguments.get("mode", "map")
            kwargs = {}
            if mode == "density" and "density" in arguments:
                mode = f"density:{arguments['density']}"
            if arguments.get("ref"):
                kwargs["ref"] = arguments["ref"]
            result = FileReadCompressor.read(path, mode=mode, **kwargs)
            # Log to index
            log_event(
                kind="file_read",
                description=f"{mode}:{path}",
                raw_tokens=rough_token_count(result.get("content", "")),
                compressed_tokens=result.get("compressed_tokens", 0),
                metadata={"file": path, "mode": mode},
                files=[{"path": path, "mode": mode, "compression_pct": result.get("compression_pct", 0)}],
            )
            return {"content": [{"type": "text", "text": json.dumps(result, indent=2, default=str)}]}

        elif name == "compress_shell":
            cmd = arguments["command"]
            timeout = arguments.get("timeout", 30)
            import subprocess
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, shell=True, timeout=timeout)
                output = r.stdout + r.stderr
            except subprocess.TimeoutExpired:
                return {"content": [{"type": "text", "text": f"Command timed out after {timeout}s"}], "isError": True}
            result = ShellOutputCompressor.compress(cmd, output)
            log_event(
                kind="shell",
                description=f"{result['handler']}:{cmd[:80]}",
                raw_tokens=result["raw_tokens"],
                compressed_tokens=result["compressed_tokens"],
                metadata={"command": cmd, "handler": result["handler"]},
            )
            return {"content": [{"type": "text", "text": json.dumps(result, indent=2, default=str)}]}

        elif name == "search_savings":
            query = arguments["query"]
            kind = arguments.get("kind")
            since = arguments.get("since")
            limit = arguments.get("limit", 10)
            results = search_events(query, limit=limit, kind=kind, since=since)
            return {"content": [{"type": "text", "text": json.dumps(results, indent=2, default=str)}]}

        elif name == "search_files":
            query = arguments["query"]
            limit = arguments.get("limit", 10)
            results = search_files(query, limit=limit)
            return {"content": [{"type": "text", "text": json.dumps(results, indent=2, default=str)}]}

        elif name == "get_stats":
            stats = stats_summary()
            return {"content": [{"type": "text", "text": json.dumps(stats, indent=2, default=str)}]}

        elif name == "get_config":
            cfg = read_config() or {}
            return {"content": [{"type": "text", "text": json.dumps(cfg, indent=2, default=str)}]}

        elif name == "sql_query":
            query = arguments["query"]
            results = sql_query(query)
            return {"content": [{"type": "text", "text": json.dumps(results, indent=2, default=str)}]}

        else:
            return {"content": [{"type": "text", "text": f"Unknown tool: {name}"}], "isError": True}

    except Exception as e:
        return {"content": [{"type": "text", "text": f"Error: {e}"}], "isError": True}


# ---------------------------------------------------------------------------
# MCP JSON-RPC server (stdio transport)
# ---------------------------------------------------------------------------

def run_mcp_stdio():
    """Run MCP server over stdin/stdout (JSON-RPC 2.0)."""
    init_db()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue

        method = msg.get("method", "")
        msg_id = msg.get("id")
        params = msg.get("params", {})

        if method == "initialize":
            response = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {
                        "name": "token-saver",
                        "version": "9.0",
                    },
                },
            }
        elif method == "notifications/initialized":
            continue  # no response needed
        elif method == "tools/list":
            response = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {"tools": TOOLS},
            }
        elif method == "tools/call":
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})
            result = handle_tool(tool_name, arguments)
            response = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": result,
            }
        else:
            response = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            }

        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()


# ---------------------------------------------------------------------------
# HTTP transport (for remote/IDE integration)
# ---------------------------------------------------------------------------

def run_mcp_http(port: int = None):
    """Run MCP server over HTTP (SSE transport)."""
    import http.server
    import threading

    port = port or MCP_PORT
    init_db()

    class MCPHandler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            try:
                msg = json.loads(body)
            except json.JSONDecodeError:
                self.send_response(400)
                self.end_headers()
                return

            method = msg.get("method", "")
            msg_id = msg.get("id")
            params = msg.get("params", {})

            if method == "initialize":
                result = {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "token-saver", "version": "9.0"},
                }
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "tools/call":
                result = handle_tool(params.get("name", ""), params.get("arguments", {}))
            else:
                self.send_response(404)
                self.end_headers()
                return

            response = json.dumps({"jsonrpc": "2.0", "id": msg_id, "result": result})
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(response.encode())

        def do_GET(self):
            if self.path == "/health":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "running", "port": port}).encode())
            elif self.path == "/tools":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(TOOLS, indent=2).encode())
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, *a):
            pass

    server = http.server.HTTPServer(("127.0.0.1", port), MCPHandler)

    # Save config
    MCP_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    MCP_CONFIG.write_text(json.dumps({
        "port": port, "enabled": True,
        "pid": os.getpid(), "transport": "http",
    }, indent=2), encoding="utf-8")

    print(f"Token Saver MCP server running on http://127.0.0.1:{port}")
    print(f"Tools: {', '.join(t['name'] for t in TOOLS)}")
    server.serve_forever()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Token Saver MCP Server")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--port", type=int, default=MCP_PORT)
    args = parser.parse_args()

    if args.transport == "stdio":
        run_mcp_stdio()
    else:
        run_mcp_http(args.port)
