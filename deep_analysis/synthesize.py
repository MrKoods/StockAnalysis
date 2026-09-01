"""
Stage 2 — hand the findings bundle to Claude and get back the written briefing.

Uses the official Anthropic SDK (`anthropic`), Claude Opus 5, adaptive thinking,
streamed so a long briefing doesn't hit the HTTP timeout. The `anthropic`
package is imported lazily and the client can be injected, so `collect` and
`render` (and their tests) don't need the dependency or an API key.
"""

from __future__ import annotations

from typing import Any

from shared.utils.logger import get_logger
from deep_analysis.prompts import SYSTEM_PROMPT, build_user_prompt

logger = get_logger(__name__)

DEFAULT_MODEL = "claude-opus-5"
DEFAULT_EFFORT = "high"
DEFAULT_MAX_TOKENS = 64_000


class SynthesisError(RuntimeError):
    """Raised when the model call cannot produce a briefing (missing dep, refusal, empty)."""


def _make_client():
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - exercised via injected client in tests
        raise SynthesisError(
            "the `anthropic` package is not installed — run `pip install anthropic` "
            "(it is in requirements.txt) to use the synthesis stage."
        ) from exc
    try:
        return anthropic.Anthropic()
    except Exception as exc:  # noqa: BLE001 - surfaces as a clean CLI error
        raise SynthesisError(f"could not construct the Anthropic client: {exc}") from exc


def synthesize(
    findings: dict,
    *,
    client: Any = None,
    model: str = DEFAULT_MODEL,
    effort: str = DEFAULT_EFFORT,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> dict:
    """
    Generate the deep-analysis briefing for a findings bundle.

    client: an Anthropic client (or anything exposing the same
            `messages.stream(...)` context manager). Constructed from the
            environment when omitted.

    Returns {"report_markdown", "model", "stop_reason", "usage"}.
    Raises SynthesisError on a refusal or an empty response.
    """
    client = client or _make_client()
    user_prompt = build_user_prompt(findings)

    logger.info(f"deep_analysis: synthesizing briefing for {findings.get('ticker', '?')} via {model}")
    try:
        with client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            thinking={"type": "adaptive"},
            output_config={"effort": effort},
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        ) as stream:
            message = stream.get_final_message()
    except SynthesisError:
        raise
    except Exception as exc:  # noqa: BLE001 - includes anthropic.APIError subclasses
        raise SynthesisError(f"the model request failed: {exc}") from exc

    stop_reason = getattr(message, "stop_reason", None)
    if stop_reason == "refusal":
        details = getattr(message, "stop_details", None)
        raise SynthesisError(f"the model declined this request (refusal): {details}")

    text = "".join(
        block.text for block in getattr(message, "content", []) if getattr(block, "type", None) == "text"
    ).strip()
    if not text:
        raise SynthesisError(f"the model returned no text (stop_reason={stop_reason}).")

    usage = getattr(message, "usage", None)
    return {
        "report_markdown": text,
        "model": getattr(message, "model", model),
        "stop_reason": stop_reason,
        "usage": {
            "input_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
        }
        if usage is not None
        else {},
    }
