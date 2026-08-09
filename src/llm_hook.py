"""
Optional LLM assistance - OFF by default.

The prototype is fully functional with zero API calls (rule-based
tagging + extractive summaries). This module exists only so a team that
wants nicer evidence notes / brief prose can flip one flag on.

Cost-conscious by design:
- Only called for short summarization/structuring, never bulk page dumps.
- Caps input to ~1500 chars per call.
- Any failure silently falls back to the rule-based text already computed
  by the caller - the pipeline never depends on this module succeeding.

Supported backends (set LLM_BACKEND env var):
- "none"    (default) - this module is not used at all.
- "openai"  - uses OPENAI_API_KEY, requests library, chat completions.
- "ollama"  - local model via http://localhost:11434, zero API cost.
"""

import os
import json

LLM_BACKEND = os.environ.get("LLM_BACKEND", "none").lower()


def llm_available() -> bool:
    return LLM_BACKEND in ("openai", "ollama")


def summarize_evidence(vendor_name: str, tag_hint: list, text: str, fallback: str) -> str:
    """Return a 1-2 sentence evidence note, or `fallback` if LLM is off/fails."""
    if not llm_available():
        return fallback
    prompt = (
        f"You are assisting with first-pass public vendor research for '{vendor_name}'. "
        f"Relevant categories: {', '.join(tag_hint) if tag_hint else 'general'}. "
        "In one or two short factual sentences, summarize only what this excerpt states. "
        "Do not add claims that are not in the text. Do not evaluate risk.\n\n"
        f"Excerpt:\n{text[:1500]}"
    )
    try:
        if LLM_BACKEND == "openai":
            return _call_openai(prompt) or fallback
        if LLM_BACKEND == "ollama":
            return _call_ollama(prompt) or fallback
    except Exception:
        return fallback
    return fallback


def _call_openai(prompt: str):
    import requests
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None
    resp = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 120,
            "temperature": 0.2,
        },
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()


def _call_ollama(prompt: str):
    import requests
    resp = requests.post(
        "http://localhost:11434/api/generate",
        json={"model": os.environ.get("OLLAMA_MODEL", "llama3.1"), "prompt": prompt, "stream": False},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("response", "").strip()
