from .upstream import complete


def ask(prompt, model="", system=None, reasoning_effort=None):
    """One-shot prompt. Default model auto-picks by difficulty (easy->free, hard->paid)."""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    data = complete(
        {"messages": messages, "max_tokens": 2048, "temperature": 0.7},
        model_hint=model,
        text=prompt,
        reasoning_effort=reasoning_effort,
    )
    return (data["choices"][0]["message"]["content"] or "").strip()
