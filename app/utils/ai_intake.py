"""AI-assisted ticket intake helpers.

This module is intentionally provider-agnostic and uses the same OpenAI-compatible
settings as the changelog AI integration.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from .ai_changelog import get_ai_config

logger = logging.getLogger(__name__)

_ALLOWED_PRIORITIES = {"urgent", "high", "medium", "low", "none"}


def _clamp_confidence(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.5
    return max(0.0, min(1.0, parsed))


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _fallback_priority(text: str) -> str:
    lowered = text.lower()
    if any(token in lowered for token in ["critical", "outage", "down", "urgent", "data loss"]):
        return "urgent"
    if any(token in lowered for token in ["broken", "fails", "error", "cannot", "can't", "fail"]):
        return "high"
    if any(token in lowered for token in ["slow", "improve", "enhance", "cleanup"]):
        return "medium"
    return "low"


def _fallback_project(text: str, projects: list[dict[str, str]]) -> str | None:
    lowered = text.lower()
    best_project_id = None
    best_score = 0

    for project in projects:
        project_id = (project.get("id") or "").strip()
        project_name = (project.get("name") or "").strip()
        if not project_id:
            continue

        score = 0
        id_token = project_id.lower()
        if id_token and id_token in lowered:
            score += 3

        for token in re.split(r"[^a-zA-Z0-9]+", project_name.lower()):
            if token and token in lowered:
                score += 1

        if score > best_score:
            best_score = score
            best_project_id = project_id

    if best_score == 0:
        return None

    return best_project_id


def _fallback_suggestion(
    message: str,
    projects: list[dict[str, str]],
    reason: str,
) -> dict[str, Any]:
    normalized = _normalize_text(message)
    title = normalized.split(".")[0][:120] if normalized else "New intake ticket"
    project_id = _fallback_project(normalized, projects)

    confidence = 0.45
    if project_id:
        confidence = 0.7

    route = "direct" if project_id and confidence >= 0.8 else "intake"

    return {
        "title": title or "New intake ticket",
        "description": normalized,
        "priority": _fallback_priority(normalized),
        "suggested_project": project_id,
        "confidence": confidence,
        "reason": reason,
        "route": route,
        "source": "fallback",
    }


def _parse_model_json(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    return json.loads(text)


def suggest_intake_from_message(message: str, projects: list[dict[str, str]]) -> dict[str, Any]:
    """Return a structured intake suggestion from chat-like user input.

    If AI is unavailable, this function returns a heuristic fallback suggestion
    instead of raising, so non-AI workflows remain usable.
    """
    normalized = _normalize_text(message)
    if not normalized:
        raise ValueError("Message is required")

    config = get_ai_config()
    if not config:
        return _fallback_suggestion(
            normalized,
            projects,
            "AI is not configured, using fallback suggestion.",
        )

    try:
        import openai
    except ImportError:
        return _fallback_suggestion(
            normalized,
            projects,
            "openai package is missing, using fallback suggestion.",
        )

    project_lines = [f"- {p.get('id')}: {p.get('name')}" for p in projects if p.get("id")]
    project_text = "\n".join(project_lines) if project_lines else "- (none available)"

    prompt = f"""You are an intake assistant for issue tracking.
Given a user message, produce a JSON object with:
- title (short, 5-12 words)
- description (cleaned and actionable)
- priority (one of: urgent, high, medium, low, none)
- suggested_project (project id or null)
- confidence (0 to 1)
- reason (one sentence why project/priority was chosen)

Available projects:
{project_text}

Rules:
- If uncertain about project, set suggested_project to null.
- Use high confidence only when project match is clear.
- Output JSON only.

User message:
{normalized}
"""

    base_url = config.get("base_url", "https://api.openai.com/v1")
    model = config.get("model", "gpt-4o-mini")

    try:
        client = openai.OpenAI(api_key=config["api_key"], base_url=base_url)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": "You output only valid JSON with the required keys.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=450,
        )

        parsed = _parse_model_json(response.choices[0].message.content or "")

        title = _normalize_text(str(parsed.get("title", "") or ""))[:140] or normalized[:120]
        description = _normalize_text(str(parsed.get("description", "") or "")) or normalized

        priority = str(parsed.get("priority", "medium") or "medium").lower()
        if priority not in _ALLOWED_PRIORITIES:
            priority = "medium"

        suggested_project = parsed.get("suggested_project")
        if suggested_project is None:
            normalized_project = None
        else:
            normalized_project = str(suggested_project).strip() or None

        project_ids = {str(p.get("id")) for p in projects if p.get("id")}
        if normalized_project and normalized_project not in project_ids:
            normalized_project = None

        confidence = _clamp_confidence(parsed.get("confidence", 0.5))
        reason = _normalize_text(str(parsed.get("reason", "") or "")) or "AI suggestion generated."

        route = "direct" if normalized_project and confidence >= 0.8 else "intake"

        return {
            "title": title,
            "description": description,
            "priority": priority,
            "suggested_project": normalized_project,
            "confidence": confidence,
            "reason": reason,
            "route": route,
            "source": "ai",
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("AI intake suggestion failed: %s", exc)
        return _fallback_suggestion(
            normalized,
            projects,
            "AI request failed, using fallback suggestion.",
        )
