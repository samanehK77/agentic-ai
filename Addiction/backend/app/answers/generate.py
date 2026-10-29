"""One model call with at most ONE repair call, and the mapping of provider failures to API errors."""
import json
import logging

from pydantic import ValidationError

from app.errors import ApiError
from app.llm import prompt as prompts
from app.llm.base import (
    BaseLLMClient, LLMBadOutput, LLMBusy, LLMError, LLMMessage, LLMNotConfigured, LLMTimeout, LLMUnavailable)
from app.llm.schema import ModelAnswer, describe_errors

logger = logging.getLogger("mindevidence.answers")


def parse(text: str) -> ModelAnswer:
    return ModelAnswer.model_validate(json.loads(text))


def llm_error(error: LLMError) -> ApiError:
    if isinstance(error, LLMNotConfigured):
        return ApiError(503, "llm_not_configured", "The language model is not configured on this server.")
    if isinstance(error, LLMTimeout):
        return ApiError(504, "llm_timeout", "The language model did not answer in time. Please try again.")
    if isinstance(error, LLMBusy):
        return ApiError(503, "llm_unavailable", "The language model is busy with another question. Please try again in a moment.",
                        headers={"Retry-After": str(error.retry_after or 30)})
    if isinstance(error, LLMUnavailable):
        headers = {"Retry-After": str(error.retry_after)} if error.retry_after else None
        return ApiError(503, "llm_unavailable", "The language model service is not available right now. Please try again later.",
                        headers=headers)
    return ApiError(502, "llm_bad_output", "The language model returned an answer that could not be used.")


def why(error: Exception) -> str:
    """A safe reason for the log: field paths and error types, or the position of a JSON syntax error. Never the text."""
    if isinstance(error, json.JSONDecodeError):
        return f"not valid json (syntax error at character {error.pos})"
    return describe_errors(error)


def generate(client: BaseLLMClient, messages: list[LLMMessage], timeout: float | None = None) -> tuple[ModelAnswer, dict]:
    """One call, plus at most ONE repair call when the output is unusable. Returns the parsed answer and usage numbers.
    `timeout` is the time left for the whole workflow (it caps every call, retries included)."""
    if not client.configured:
        raise ApiError(503, "llm_not_configured", "The language model is not configured on this server.")
    usage = {"model": None, "prompt_tokens": 0, "completion_tokens": 0, "retries": 0, "repair_attempted": False}

    def call(msgs: list[LLMMessage]):
        try:
            result = client.complete(msgs, json_mode=True, timeout=timeout)
        except LLMBadOutput:
            raise
        except LLMError as error:
            raise llm_error(error) from None
        usage["model"] = result.model
        usage["prompt_tokens"] += result.prompt_tokens
        usage["completion_tokens"] += result.completion_tokens
        usage["retries"] += result.retries
        return result

    problems = "the reply was empty or cut off"
    first_text = None
    try:
        first = call(messages)
        first_text = first.text
        return parse(first.text), usage
    except LLMBadOutput as error:
        logger.warning("model output unusable (attempt 1): %s", error)  # a generic reason, never the output itself
    except (ValueError, ValidationError) as error:
        problems = describe_errors(error)
        logger.warning("model output rejected (attempt 1): %s", why(error))

    usage["repair_attempted"] = True
    repair = list(messages)
    if first_text is not None:
        repair += [LLMMessage("assistant", first_text[:4000]),
                   LLMMessage("user", prompts.load_prompt("repair_v1.txt").format(problems=problems))]
    try:
        second = call(repair)
        return parse(second.text), usage
    except LLMBadOutput as error:
        logger.warning("model output unusable (attempt 2, after the repair request): %s", error)
        raise ApiError(502, "llm_bad_output", "The language model returned an answer that could not be used.") from None
    except (ValueError, ValidationError) as error:
        logger.warning("model output rejected (attempt 2, after the repair request): %s", why(error))
        raise ApiError(502, "llm_bad_output", "The language model returned an answer that could not be used.") from None
