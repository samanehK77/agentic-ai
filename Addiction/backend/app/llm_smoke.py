"""One tiny REAL call to the language model, to check that the key, model name and request format are accepted.

    python -m app.llm_smoke --live

It refuses to run without --live, and --live must only be used after the project owner has explicitly approved a live
call. It sends one short message (no patient data, no document text), prints the status, the model id and the token
counts, and never prints the key. With a local model server (DEEPSEEK_BASE_URL=http://localhost:11434/v1) nothing
leaves this computer.
"""
import argparse
import sys

from app.llm.base import LLMError, LLMMessage
from app.llm.config import LLMConfigError, load_llm_settings
from app.llm.deepseek import DeepSeekClient


def main(argv: list[str] | None = None, *, client=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.llm_smoke", description="One tiny real call to the model.")
    parser.add_argument("--live", action="store_true", help="really call the provider (needs explicit approval)")
    parser.add_argument("--max-tokens", type=int, default=30, help="output limit of the tiny call (thinking models may need more)")
    args = parser.parse_args(argv)
    if not args.live:
        print("Refusing to run: this makes a real call to the language model provider. Run it with --live only after "
              "the project owner has approved a live call.", file=sys.stderr)
        return 2
    try:
        settings = load_llm_settings()
    except LLMConfigError as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return 2
    if not settings.configured and client is None:
        print("No DEEPSEEK_API_KEY is configured (and DEEPSEEK_BASE_URL is not a local address); nothing was sent.", file=sys.stderr)
        return 2
    client = client or DeepSeekClient(settings)
    messages = [LLMMessage("system", "You reply with a single json object and nothing else."),
                LLMMessage("user", 'Return the json object {"ok": true}.')]
    try:
        result = client.complete(messages, json_mode=True, max_tokens=args.max_tokens, temperature=0.0)
    except LLMError as error:
        print(f"The call failed: {type(error).__name__}", file=sys.stderr)
        return 1
    print(f"OK: model={result.model} finish={result.finish_reason} prompt_tokens={result.prompt_tokens} "
          f"completion_tokens={result.completion_tokens} retries={result.retries} reply_characters={len(result.text)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
