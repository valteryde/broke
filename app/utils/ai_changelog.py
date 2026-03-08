"""
AI Changelog Summarizer

Uses an OpenAI-compatible API to generate clean changelog entries
from ticket data. Fully optional — if no API key is configured,
all AI features are hidden from the UI.
"""

import json
import logging
import os
from .models import GlobalSetting, Ticket, Comment

logger = logging.getLogger(__name__)


def get_ai_config() -> dict | None:
    """
    Returns AI configuration from GlobalSetting, or None if not configured.
    Keys: ai_api_key, ai_api_base_url
    """
    try:
        setting = GlobalSetting.get(GlobalSetting.key == "ai_settings")
        config = json.loads(setting.value)
        if config.get("api_key"):
            return config
    except (GlobalSetting.DoesNotExist, json.JSONDecodeError):
        pass

    # .env / environment fallback for local testing and non-UI setup.
    api_key = (
        os.environ.get("AI_API_KEY", "").strip()
        or os.environ.get("OPENAI_API_KEY", "").strip()
        or os.environ.get("BROKE_AI_API_KEY", "").strip()
    )
    if not api_key:
        return None

    return {
        "api_key": api_key,
        "base_url": os.environ.get("AI_BASE_URL", "").strip()
        or os.environ.get("OPENAI_BASE_URL", "").strip()
        or "https://api.openai.com/v1",
        "model": os.environ.get("AI_MODEL", "").strip() or "gpt-4o-mini",
    }


def is_ai_enabled() -> bool:
    """Check if AI features are configured and available."""
    return get_ai_config() is not None


def summarize_single_ticket(ticket: Ticket, language: str = "English") -> str:
    """
    Send ticket data to an LLM and get back a user-friendly one-sentence summary.

    Args:
        ticket: Ticket object (with comments/labels populated)
        language: The target language for the summary (e.g. 'English', 'Danish')

    Returns:
        str: A single sentence translating the technical ticket into user-friendly phrasing.

    Raises:
        ValueError: If AI is not configured
        RuntimeError: If the API call fails
    """
    config = get_ai_config()
    if not config:
        raise ValueError("AI is not configured. Set API key in Settings → AI Integration.")

    try:
        import openai
    except ImportError:
        raise RuntimeError("openai package is not installed. Run: pip install openai")

    # Gather comments
    comments = Comment.select().where(Comment.ticket == ticket.id).order_by(Comment.id)
    comment_texts = [c.body for c in comments]

    ticket_info = {
        "id": ticket.id,
        "title": ticket.title,
        "description": ticket.description[:1000] if ticket.description else "",
        "status": ticket.status,
    }
    if comment_texts:
        ticket_info["comments"] = comment_texts[:5]  # Limit to avoid token overflow

    # Add labels if populated
    if hasattr(ticket, "labels") and ticket.labels:
        ticket_info["labels"] = [
            l.name for l in ticket.labels if l is not None
        ]

    prompt = f"""You are a technical writer helping to build a public changelog. 
I will give you the raw details of an internal development ticket (title, description, and comments).

Your job is to translate this technical jargon into a single, user-friendly, professional sentence explaining what improved or was fixed for the end-user. 
Do not mention the ticket ID or internal engineering details. Focus on the value delivered to the user.

Output language: {language}

Output ONLY the translated sentence, without quotes or formatting.

Ticket Details:
{json.dumps(ticket_info, indent=2)}"""

    base_url = config.get("base_url", "https://api.openai.com/v1")
    model = config.get("model", "gpt-4o-mini")

    client = openai.OpenAI(
        api_key=config["api_key"],
        base_url=base_url,
    )

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a concise technical writer. Output exactly one sentence."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=200,
        )

        content = response.choices[0].message.content.strip()
        
        # Strip quotes if the LLM wrapped it anyway
        if content.startswith('"') and content.endswith('"'):
            content = content[1:-1]
            
        return content

    except openai.APIError as e:
        raise RuntimeError(f"AI API error: {e}")


def generate_full_changelog(tickets_with_categories: list[dict], language: str = "English") -> dict:
    """
    Generate a complete changelog from a list of tickets with their categories.

    Each item in tickets_with_categories is:
        {"ticket_id": "DOC-105", "category": "new", "title": "...", "description": "..."}

    Returns:
        {
            "title": "Suggested release title",
            "entries": [
                {"ticket_id": "DOC-105", "category": "new", "text": "User-friendly summary"},
                ...
            ]
        }

    Raises:
        ValueError: If AI is not configured
        RuntimeError: If the API call fails
    """
    config = get_ai_config()
    if not config:
        raise ValueError("AI is not configured.")

    try:
        import openai
    except ImportError:
        raise RuntimeError("openai package is not installed. Run: pip install openai")

    # Build ticket info for each ticket
    tickets_info = []
    for item in tickets_with_categories:
        ticket = Ticket.get_or_none(Ticket.id == item["ticket_id"])
        if not ticket:
            continue

        comments = Comment.select().where(Comment.ticket == ticket.id).order_by(Comment.id).limit(5)
        comment_texts = [c.body for c in comments]

        info = {
            "ticket_id": ticket.id,
            "title": ticket.title,
            "description": (ticket.description[:500] if ticket.description else ""),
            "status": ticket.status,
            "type": ticket.category if hasattr(ticket, 'category') else "unknown"
        }
        if comment_texts:
            info["comments"] = comment_texts[:3]
        tickets_info.append(info)

    if not tickets_info:
        raise ValueError("No valid tickets provided.")

    prompt = f"""You are a technical writer creating a public changelog for a software product.

I will give you a list of internal development tickets.

Your tasks:
1. Suggest a short, engaging release title (3-6 words, no version numbers).
2. For EACH ticket, determine if the change represents a "new" feature, a "changed" improvement/modification, or a "fixed" bug based on its title and description.
3. For EACH ticket, write a single user-friendly sentence explaining the change from the user's perspective.
   - Use "we have" phrasing (e.g., "We have added...", "We have improved...", "We have fixed...").
   - Do NOT mention ticket IDs or internal engineering details.
   - Focus on the value delivered to the end user.

Categories available to choose from: "new" (New Feature), "changed" (Improvement), "fixed" (Bug Fix).

Output language: {language}

Return valid JSON in this exact format (no markdown fences, no extra text):
{{
    "title": "Your suggested title",
    "entries": [
        {{"ticket_id": "<original ticket_id>", "category": "<new, changed, or fixed>", "text": "User-friendly summary sentence"}}
    ]
}}

Tickets:
{json.dumps(tickets_info, indent=2)}"""

    base_url = config.get("base_url", "https://api.openai.com/v1")
    model = config.get("model", "gpt-4o-mini")

    client = openai.OpenAI(
        api_key=config["api_key"],
        base_url=base_url,
    )

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": "You are a concise technical writer. Output only valid JSON, no markdown fences.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=1500,
        )

        raw = response.choices[0].message.content.strip()

        # Strip markdown fences if the model adds them anyway
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1]  # Remove first line
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()

        result = json.loads(raw)

        # Validate structure
        if "title" not in result or "entries" not in result:
            raise ValueError("AI returned invalid structure")

        return result

    except json.JSONDecodeError as e:
        raise RuntimeError(f"AI returned invalid JSON: {e}")
    except openai.APIError as e:
        raise RuntimeError(f"AI API error: {e}")
