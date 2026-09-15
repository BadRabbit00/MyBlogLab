"""LLM client interface for blog-agent targeting llama-server with Gemma 4.

Implements token formatting, exponential backoff retries, thought channel stripping,
and structured per-post JSONL logging.
"""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import time
from typing import Optional

import httpx

from src.logger import get_logger
from src.paths import DATA_DIR
from src.validation import PLAIN_TEXT_INSTRUCTION, ResponseValidationError, validate_plain_text

logger = get_logger("llm")

LOGS_DIR: Path = DATA_DIR / "logs"
DEFAULT_ENDPOINT: str = "http://127.0.0.1:8080/completion"

PRESETS: dict[str, dict[str, object]] = {
    "draft": {
        "temperature": 0.8,
        "top_p": 0.95,
        "repeat_penalty": 1.1,
        "n_predict": 1200,
    },
    "critique": {
        "temperature": 0.3,
        "top_p": 0.90,
        "repeat_penalty": 1.05,
        "n_predict": 3072,
    },
    "extract": {
        "temperature": 0.1,
        "top_p": 0.90,
        "n_predict": 512,
    },
}


@dataclass
class LLMResponse:
    """Container for raw and sanitised LLM responses."""

    raw_content: str
    cleaned_content: str
    tokens_predicted: int
    duration_ms: float
    model_name: str


def format_gemma4_prompt(system_prompt: str, user_prompt: str, enable_thinking: bool = False) -> str:
    """Format prompt with exact Gemma 4 turn tokens.

    Gemma 4 format:
    <|turn>system
    [<|think|>]
    {system_prompt}<turn|>
    <|turn>user
    {user_prompt}<turn|>
    <|turn>model
    """
    sys_body: str = f"<|think|>\n{system_prompt}" if enable_thinking else system_prompt
    return (
        f"<|turn>system\n{sys_body.strip()}<turn|>\n"
        f"<|turn>user\n{user_prompt.strip()}<turn|>\n"
        f"<|turn>model\n"
    )


def sanitize_response(raw_text: str) -> str:
    """Strip Gemma 4 internal thought channel and artifact tokens.

    Removes a leading <|channel>thought ... <channel|>, trailing Gemma tokens,
    and accidental conversational prefixes. Keep content markup for validation.
    """
    # 1. Thought channel extraction
    cleaned = raw_text.strip()
    if cleaned.startswith("<|channel>thought"):
        _, closing_token, cleaned = cleaned.partition("<channel|>")
        if not closing_token:
            raise ValueError("Model was cut off inside thinking channel before outputting response")

    # Only trailing protocol tokens are transport metadata. Tags inside the answer
    # (including <s>, which is HTML strikethrough) must reach the validator.
    cleaned = re.sub(r"(?:\s*(?:<turn\|>|<eos>))+\s*$", "", cleaned).strip()

    # Strip accidental conversational prefixes like "Вот черновик:" or "Вот пост:"
    prefix_patterns = [
        r"^(?:Вот (?:готовый )?(?:пост|черновик|текст|вариант)|Исправленный вариант):\s*\n*",
        r"^(?:Черновик|Текст поста):\s*\n*",
    ]
    for pattern in prefix_patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE).strip()

    return cleaned


def log_interaction(
    post_id: str,
    step: str,
    prompt: str,
    response_data: dict[str, object],
    cleaned_output: str,
    duration_ms: float,
    validation_errors: Optional[list[str]] = None,
) -> None:
    """Record LLM prompt, parameters, and response to logs/{post_id}.jsonl."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOGS_DIR / f"{post_id}.jsonl"

    record: dict[str, object] = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "post_id": post_id,
        "step": step,
        "duration_ms": duration_ms,
        "prompt": prompt,
        "cleaned_output": cleaned_output,
        "raw_response": response_data,
        "validation_errors": validation_errors or [],
    }

    with open(log_file, "a", encoding="utf-8", errors="backslashreplace") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def generate(
    post_id: str,
    step: str,
    system_prompt: str,
    user_prompt: str,
    enable_thinking: bool = False,
    preset: str = "draft",
    custom_params: Optional[dict[str, object]] = None,
    endpoint: Optional[str] = None,
    max_retries: int = 3,
    timeout_sec: float = 120.0,
) -> LLMResponse:
    """Call llama-server completion API with exponential backoff and structured logging."""
    endpoint = endpoint or os.getenv("LLM_ENDPOINT", DEFAULT_ENDPOINT)
    system_prompt = f"{system_prompt.strip()}\n\n{PLAIN_TEXT_INSTRUCTION}"
    full_prompt: str = format_gemma4_prompt(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        enable_thinking=enable_thinking,
    )

    sampling_params: dict[str, object] = dict(PRESETS.get(preset, PRESETS["draft"]))
    if custom_params:
        sampling_params.update(custom_params)

    payload: dict[str, object] = {
        "prompt": full_prompt,
        "stream": False,
        **sampling_params,
    }

    last_error: Optional[Exception] = None

    for attempt in range(1, max_retries + 1):
        start_time = time.monotonic()
        try:
            with httpx.Client(timeout=timeout_sec) as client:
                response = client.post(endpoint, json=payload)
                response.raise_for_status()
                data: dict[str, object] = response.json()
                if not isinstance(data, dict):
                    raise ValueError("Completion API response must be a JSON object")

            duration_ms = round((time.monotonic() - start_time) * 1000, 2)
            raw_text = data.get("content")
            cleaned_text = sanitize_response(raw_text) if isinstance(raw_text, str) else ""
            validation_errors = validate_plain_text(cleaned_text if isinstance(raw_text, str) else raw_text)

            log_interaction(
                post_id=post_id,
                step=step,
                prompt=full_prompt,
                response_data=data,
                cleaned_output=cleaned_text,
                duration_ms=duration_ms,
                validation_errors=validation_errors,
            )

            if validation_errors:
                raise ResponseValidationError(validation_errors)

            tokens_predicted = int(data.get("tokens_predicted", 0))
            model_name = str(data.get("model", "gemma-4-12b"))

            return LLMResponse(
                raw_content=raw_text,
                cleaned_content=cleaned_text,
                tokens_predicted=tokens_predicted,
                duration_ms=duration_ms,
                model_name=model_name,
            )

        except ResponseValidationError as exc:
            last_error = exc
            logger.warning(f"Rejected model answer for {post_id} ({step}, attempt {attempt}): {exc}")
            full_prompt = format_gemma4_prompt(
                system_prompt=system_prompt,
                user_prompt=user_prompt + "\n\nПредыдущий ответ отклонён валидатором:\n"
                + "\n".join(exc.errors) + "\nПерепиши ответ, устранив эти нарушения.",
                enable_thinking=enable_thinking,
            )
            # Replace the payload so each logged/sent attempt retains its own prompt.
            payload = {**payload, "prompt": full_prompt}
        except (httpx.HTTPError, ValueError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < max_retries:
                backoff = 2.0 ** attempt
                time.sleep(backoff)

    if isinstance(last_error, ResponseValidationError):
        raise last_error

    raise RuntimeError(
        f"Failed to generate output for post '{post_id}' at step '{step}' after {max_retries} attempts: {last_error}"
    )
