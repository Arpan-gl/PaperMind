"""
PaperMind — OpenRouter Client
Source: docs/architecture.md

Wraps the OpenAI SDK to call Qwen3:32B via OpenRouter.
    Model ID : qwen/qwen3-32b
    Base URL : https://openrouter.ai/api/v1
    Cost     : ~$0.003 per paper ingested
"""

import os
import json
import asyncio
import logging
from typing import Optional

from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("papermind.openrouter")

# ── Configuration from architecture.md ──────────────────────────
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
MODEL_ID = "qwen/qwen3-32b"
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2  # seconds


def get_client() -> AsyncOpenAI:
    """Create an AsyncOpenAI client pointing at OpenRouter."""
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError(
            "OPENROUTER_API_KEY not set. "
            "Copy .env.example to .env and add your key."
        )
    return AsyncOpenAI(
        api_key=api_key,
        base_url=OPENROUTER_BASE_URL,
        timeout=120.0,
    )


async def qwen_call(
    system_prompt: str,
    user_message: str,
    temperature: float = 0.3,
    max_tokens: int = 8192,
    json_mode: bool = True,
) -> str:
    """
    Call Qwen3:32B via OpenRouter with retry on rate-limit.

    Args:
        system_prompt: The system instruction for the agent.
        user_message:  The user-facing input (PDF text, question, etc.).
        temperature:   Sampling temperature (low for extraction).
        max_tokens:    Maximum response tokens.
        json_mode:     If True, request JSON response format.

    Returns:
        Raw string response content from the model.
    """
    client = get_client()

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]

    kwargs = {
        "model": MODEL_ID,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = await client.chat.completions.create(**kwargs)
            content = response.choices[0].message.content
            if content is None:
                raise ValueError("Model returned empty content")
            logger.info(
                f"Qwen call succeeded (attempt {attempt}), "
                f"tokens: {response.usage.prompt_tokens}+{response.usage.completion_tokens}"
            )
            return content.strip()

        except Exception as e:
            error_str = str(e).lower()
            is_rate_limit = "rate" in error_str or "429" in error_str
            is_server_error = "500" in error_str or "502" in error_str or "503" in error_str

            if (is_rate_limit or is_server_error) and attempt < MAX_RETRIES:
                wait = RETRY_BACKOFF_BASE ** attempt
                logger.warning(
                    f"Qwen call failed (attempt {attempt}/{MAX_RETRIES}): {e}. "
                    f"Retrying in {wait}s..."
                )
                await asyncio.sleep(wait)
            else:
                logger.error(f"Qwen call failed permanently: {e}")
                raise


async def qwen_call_with_history(
    system_prompt: str,
    messages_history: list[dict],
    temperature: float = 0.3,
    max_tokens: int = 8192,
) -> str:
    """
    Call Qwen3:32B with a full message history (for multi-turn conversations).

    Args:
        system_prompt:    System instruction.
        messages_history: List of {"role": "user"|"assistant", "content": "..."}.
        temperature:      Sampling temperature.
        max_tokens:       Maximum response tokens.

    Returns:
        Raw string response content from the model.
    """
    client = get_client()

    messages = [{"role": "system", "content": system_prompt}] + messages_history

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = await client.chat.completions.create(
                model=MODEL_ID,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            content = response.choices[0].message.content
            if content is None:
                raise ValueError("Model returned empty content")
            return content.strip()

        except Exception as e:
            error_str = str(e).lower()
            is_rate_limit = "rate" in error_str or "429" in error_str

            if is_rate_limit and attempt < MAX_RETRIES:
                wait = RETRY_BACKOFF_BASE ** attempt
                logger.warning(f"Rate limited, retrying in {wait}s...")
                await asyncio.sleep(wait)
            else:
                raise
