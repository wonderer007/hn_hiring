"""Thin OpenAI client for structured extraction.

Swap this module's implementation to add a second provider without
touching the pipeline — the signature of `extract_post` is the contract.
"""

from __future__ import annotations

import os

from openai import AsyncOpenAI

from .schema import ExtractionResult

EXTRACTION_MODEL: str = os.getenv("EXTRACTION_MODEL", "gpt-4o-mini")

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI()  # reads OPENAI_API_KEY from env
    return _client


async def extract_post(text: str, system_prompt: str) -> tuple[dict, int, int]:
    """Call OpenAI Structured Outputs and return (parsed_dict, input_tokens, output_tokens).

    Raises openai.RateLimitError / openai.APIStatusError on retriable failures.
    Raises openai.APIError on non-retriable failures.
    """
    completion = await _get_client().beta.chat.completions.parse(
        model=EXTRACTION_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text},
        ],
        response_format=ExtractionResult,
    )
    parsed = completion.choices[0].message.parsed
    usage = completion.usage
    return (
        parsed.model_dump(),
        usage.prompt_tokens if usage else 0,
        usage.completion_tokens if usage else 0,
    )
