"""Shared helpers for parsing LLM responses."""
import json
import re


def extract_text(content: str | list) -> str:
    """Normalize LangChain response.content (str or list of content blocks) to a string."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "\n".join(parts)
    return str(content)


def parse_llm_json(content: str | list) -> dict:
    """Extract text from an LLM response, strip markdown fences, and parse JSON."""
    text = extract_text(content).strip()
    # Strip ```json ... ``` or ``` ... ``` fences if present
    fence_match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()
    return json.loads(text)
