"""Shared helpers for invoking LLMs with retry/fallback and parsing JSON responses."""
import json
import logging
import os
import re
import time

from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI

logger = logging.getLogger(__name__)

# Ordered list of Gemini models to try if the primary model hits 503/404
DEFAULT_MODEL_CANDIDATES = [
    "gemini-3.6-flash"
]


def invoke_llm_with_fallback(
    prompt: ChatPromptTemplate,
    inputs: dict,
    temperature: float = 0.0,
):
    """Invoke a prompt against Gemini, retrying on transient 503s and falling back across models."""
    preferred = os.getenv("GEMINI_MODEL", "").strip()
    candidates = ([preferred] if preferred else []) + [
        m for m in DEFAULT_MODEL_CANDIDATES if m != preferred
    ]

    last_error: Exception | None = None
    for model_name in candidates:
        for attempt in range(2):
            try:
                llm = ChatGoogleGenerativeAI(
                    model=model_name,
                    temperature=temperature,
                    max_retries=2,
                )
                return (prompt | llm).invoke(inputs)
            except Exception as e:
                last_error = e
                err_str = str(e)
                if "503" in err_str or "UNAVAILABLE" in err_str:
                    wait_s = 3 * (attempt + 1)
                    logger.warning(
                        f"[LLM] {model_name} returned 503 UNAVAILABLE (attempt {attempt + 1}/2), "
                        f"retrying in {wait_s}s..."
                    )
                    time.sleep(wait_s)
                    continue
                if "404" in err_str or "NOT_FOUND" in err_str:
                    logger.warning(f"[LLM] {model_name} not available (404), trying next model...")
                    break
                raise

    raise last_error  # type: ignore[misc]


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
