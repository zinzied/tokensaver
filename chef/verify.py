"""Fresh-eyes verification (Fable-orchestrator inspired).

A worker builds the work; a DIFFERENT, cheap model verifies it before it is
counted as done. The verifier never saw the build, so it checks the work
itself against the task, adversarially.
"""

from .ask import ask

VERIFY_PROMPT = """You are a FRESH-EYES VERIFIER. You did not build this work and have never seen it before.
A worker claims the task below is done. Check the COMPLETED WORK strictly and adversarially against every
requirement in the TASK. Do not trust any worker summary; judge only the completed work.

TASK:
{task}

COMPLETED WORK:
{work}

Respond in exactly this format:

VERDICT: PASS
or
VERDICT: FAIL

FINDINGS:
- <issue 1>
- <issue 2>

If it passes, write:
FINDINGS:
none

Be harsh. Missing requirements, silent assumptions, and broken edge cases are FAIL."""


def verify(task, work, model="chef/qwen-coder", reasoning_effort=None, max_chars=12000):
    """Fresh-eyes check of `work` against `task` using a separate model.

    Returns {'verdict': 'PASS'|'FAIL'|'UNKNOWN', 'findings': str, 'raw': str}.
    """
    prompt = VERIFY_PROMPT.format(
        task=(task or "").strip(),
        work=(work or "").strip()[:max_chars],
    )
    raw = (ask(prompt, model=model, reasoning_effort=reasoning_effort) or "").strip()
    upper = raw.upper()
    if "VERDICT: FAIL" in upper:
        verdict = "FAIL"
    elif "VERDICT: PASS" in upper:
        verdict = "PASS"
    else:
        verdict = "UNKNOWN"
    return {"verdict": verdict, "findings": raw, "raw": raw}
