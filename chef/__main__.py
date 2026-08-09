import argparse
import sys
from pathlib import Path

# Support both `python -m chef` and a bare `python chef` directory run: the
# latter executes this file as a script with no parent package on sys.path.
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "chef"

from . import config
from .ask import ask
from .catalog import MODELS, PAID_MODELS, TIER_NAMES, escalate, recommend
from .difficulty import is_uncertain
from .plan import plan
from .proxy import serve
from .upstream import ConfigError, UpstreamError, provider_available
from .verify import verify


def _need_text(value, fallback=""):
    text = " ".join(value).strip()
    return text or fallback


def _cmd_models(_args):
    print("%-28s %-12s %-6s %s" % ("Model", "Provider", "Score", "Tags"))
    print("-" * 78)
    for m in sorted(MODELS, key=lambda x: -x["score"]):
        avail = "yes" if provider_available(m["provider"]) else "no"
        print("%-28s %-12s %-6s %s  (key set: %s)" % (
            m["id"], m["provider"], m["score"], ",".join(m["tags"]), avail))
    print("-" * 78)
    print("Paid models (used only for the expert tier, budget-capped):")
    for m in sorted(PAID_MODELS, key=lambda x: -x["score"]):
        print("%-28s %-12s %-6s %-30s $%.2f/M in" % (
            m["id"], m["provider"], m["score"], m["label"], m["usd_per_m_input"]))


def _cmd_route(args):
    task = _need_text(args.task, "Build a small web app")
    rec = recommend(task, args.max_paid)
    color = {"EASY": "green", "MEDIUM": "yellow", "HARD": "red"}[rec["label"]]
    mode = " [FREE-ONLY]" if config.FREE_ONLY else ""
    print("Task        : %s" % task[:100])
    print("Difficulty  : %s  (score %d/100)%s" % (rec["label"], rec["score"], mode))
    print("Tier        : %s  [%s]  effort=%s" % (
        rec["tier"].upper(), TIER_NAMES[rec["tier"]], rec["effort"].upper()))
    cost = "PAID" if rec["cost"] == "paid" else "FREE"
    price = "  ~$%.2f/M in" % rec["price"] if rec["cost"] == "paid" else ""
    print("Recommended : %s  [%s  %s%s]" % (rec["model_id"], cost, rec["model_label"], price))
    if rec["cost"] == "free" and rec["tier"] == "expert":
        print("(free-only / no paid within budget -> best free model you have serves the hard task)")
    higher = escalate(task, rec["model_id"], args.max_paid)
    print("Escalation  : %s" % (higher or "at ceiling (no higher tier)"))
    print("\nFallback chain (first 6 of %d):" % len(rec["chain"]))
    for i, (prov, route) in enumerate(rec["chain"][:6], 1):
        avail = "yes" if provider_available(prov) else "no"
        print("  %d. %s/%s  (key set: %s)" % (i, prov, route, avail))
    if len(rec["chain"]) > 6:
        print("  ... %d more fallbacks (auto)" % (len(rec["chain"]) - 6))


def _cmd_plan(args):
    task = _need_text(args.task, "Build a small web app")
    print("Planning with free model (auto-picked by difficulty)...")
    try:
        result = plan(task, model=args.model)
    except (UpstreamError, ConfigError) as exc:
        sys.exit("error: " + str(exc))
    print(result)
    if args.write:
        with open("TODO.md", "w", encoding="utf-8") as fh:
            fh.write("# TODO\n\n" + result + "\n")
        print("\nWrote TODO.md")


def _cmd_ask(args):
    prompt = _need_text(args.prompt, "Say hello")
    try:
        result = ask(prompt, model=args.model, reasoning_effort=args.effort)
        if args.escalate and is_uncertain(result):
            higher = escalate(prompt, args.model)
            if higher:
                print("(worker uncertain -> escalating to %s)" % higher)
                result = ask(prompt, model=higher, reasoning_effort=args.effort)
    except (UpstreamError, ConfigError) as exc:
        sys.exit("error: " + str(exc))
    print(result)


def _cmd_verify(args):
    task = _need_text(args.task, "")
    work = args.work or ""
    if args.file:
        try:
            with open(args.file, "r", encoding="utf-8") as fh:
                work = fh.read()
        except OSError as exc:
            sys.exit("error: cannot read %s: %s" % (args.file, exc))
    if not task:
        sys.exit("error: provide a task description")
    if not work:
        sys.exit("error: provide the completed work via --work or --file")
    print("Fresh-eyes verification with %s (a model that did NOT build this)...\n" % (args.model or "auto"))
    try:
        result = verify(task, work, model=args.model, reasoning_effort=args.effort)
    except (UpstreamError, ConfigError) as exc:
        sys.exit("error: " + str(exc))
    if result["verdict"] == "PASS":
        print("VERDICT: PASS")
    elif result["verdict"] == "FAIL":
        print("VERDICT: FAIL  -> fix findings and re-verify")
    else:
        print("VERDICT: UNKNOWN  (verifier did not emit a clear verdict)")
    print("\n" + result["findings"])


def main():
    parser = argparse.ArgumentParser(
        prog="chef",
        description="Chef Agent Proxy - route paid model calls from CLI IDEs to free models.",
    )
    sub = parser.add_subparsers(dest="cmd")

    p_proxy = sub.add_parser("proxy", help="Run the HTTP proxy (OpenAI + Anthropic compatible)")
    p_proxy.add_argument("--host", default=config.HOST)
    p_proxy.add_argument("--port", type=int, default=config.PORT)

    p_plan = sub.add_parser("plan", help="Generate a TODO plan with tier/effort/model per step (by difficulty)")
    p_plan.add_argument("task", nargs="*")
    p_plan.add_argument("-m", "--model", default="", help="force a chef/ or paid/ model id (default: auto by difficulty)")
    p_plan.add_argument("--write", action="store_true", help="also write TODO.md")

    p_ask = sub.add_parser("ask", help="Ask a model a question (auto: easy->free, hard->paid)")
    p_ask.add_argument("prompt", nargs="*")
    p_ask.add_argument("-m", "--model", default="", help="force a chef/ or paid/ model id (default: auto by difficulty)")
    p_ask.add_argument("--escalate", action="store_true", help="if the response signals uncertainty, retry one tier up")
    p_ask.add_argument("--effort", choices=["low", "medium", "high"], default=None,
                       help="reasoning_effort to send upstream (supported by reasoning models only)")

    p_verify = sub.add_parser("verify", help="Fresh-eyes verification: a separate cheap model checks completed work against the task")
    p_verify.add_argument("task", nargs="*")
    p_verify.add_argument("--work", default="", help="the completed work to check (or use --file)")
    p_verify.add_argument("--file", default=None, help="read the completed work from a file")
    p_verify.add_argument("-m", "--model", default="chef/qwen-coder", help="verifier model (default: free worker tier)")
    p_verify.add_argument("--effort", choices=["low", "medium", "high"], default=None,
                          help="reasoning_effort to send upstream")

    p_route = sub.add_parser("route", help="Classify a task's difficulty and recommend a model + tier")
    p_route.add_argument("task", nargs="*")
    p_route.add_argument("--max-paid", type=float, default=None,
                         help="max $/M input for the paid model (default: CHEF_MAX_PAID_USD_PER_M)")

    sub.add_parser("models", help="List available free + paid models")

    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        return

    handlers = {
        "proxy": lambda a: serve(a.host, a.port),
        "plan": _cmd_plan,
        "ask": _cmd_ask,
        "verify": _cmd_verify,
        "route": _cmd_route,
        "models": _cmd_models,
    }
    handlers[args.cmd](args)


if __name__ == "__main__":
    main()
