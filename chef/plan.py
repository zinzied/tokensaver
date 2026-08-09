from .upstream import complete

PLAN_PROMPT = """You are a Senior Staff engineer acting as the "chef orchestrator" for a money-aware AI development workflow.
Plan the following objective as a concise markdown TODO list. Rules:
- Break the work into concrete, ordered steps.
- For each step give: (1) TIER as [bulk], [worker], or [expert]; (2) the best model; (3) EFFORT as low/high/max.
- TIER by difficulty: [bulk]=mechanical volume (grep, format, rename, read, simple edits);
  [worker]=implementation, tests, debugging, refactors, routine judgment;
  [expert]=architecture, irreversible migrations, security, complex multi-system work.
- MODEL by tier: bulk and worker -> FREE models only
  (OpenRouter :free like deepseek-chat / qwen-coder / gemini-flash, Groq free tier, Google Gemini free tier, or local Ollama).
  expert -> the best free reasoning model if one fits; only if no free model fits may you write a paid
  frontier model in parentheses as a last resort.
- EFFORT by tier: low for mechanical bulk, high for worker steps, max for expert steps.
- Include an "optimized prompt" column with a short, copy-paste prompt for that step.
- END with a final [bulk] verification step: a separate fresh-eyes model checks the completed work
  against the requirements before the work is marked done.
- Keep it actionable, no fluff, markdown table or checkboxes.

Objective: {task}
Output ONLY markdown."""


def plan(task, model=""):
    """Generate a difficulty-aware TODO plan. Default model auto-picks by task difficulty."""
    data = complete(
        {"messages": [{"role": "user", "content": PLAN_PROMPT.format(task=task)}], "max_tokens": 2000},
        model_hint=model,
        text=task,
    )
    return (data["choices"][0]["message"]["content"] or "").strip()
