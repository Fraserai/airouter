#!/usr/bin/env python
"""Two bounded paid calls through the gateway, using the unmodified client SDK."""

import argparse
import json

from openai import APIError, OpenAI


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8099/v1")
    args = parser.parse_args()
    try:
        with OpenAI(base_url=args.base_url, api_key="unused", max_retries=0, timeout=60) as client:
            result = client.chat.completions.create(
                model="auto",
                messages=[{"role": "user", "content": "Say: Router is live."}],
                max_completion_tokens=32,
                extra_body={"router": {"explain": True}},
            )
            assert result.choices[0].message.content, "empty response"
            assert result.usage and result.usage.total_tokens > 0, "missing usage"
            assert result.usage.model_extra.get("estimated") is False, "requires live mode"
            print(
                json.dumps(
                    {
                        "mode": "normal",
                        "model": result.model,
                        "text": result.choices[0].message.content,
                        "tokens": result.usage.total_tokens,
                        "execution_cost_usd": result.model_extra["routing"]["execution_cost_usd"],
                    }
                )
            )
            text = ""
            usage = None
            with client.chat.completions.create(
                model="auto",
                messages=[{"role": "user", "content": "Say: Streaming works."}],
                max_completion_tokens=32,
                stream=True,
                stream_options={"include_usage": True},
            ) as stream:
                for chunk in stream:
                    if chunk.choices:
                        text += chunk.choices[0].delta.content or ""
                    if chunk.usage:
                        usage = chunk.usage
            assert text and usage and usage.total_tokens > 0, "stream missing text or usage"
            assert usage.model_extra.get("estimated") is False, "requires live mode"
            print(json.dumps({"mode": "stream", "text": text, "tokens": usage.total_tokens}))
            print("PASS: normal and streaming responses with provider-reported usage")
        return 0
    except APIError as exc:
        print(f"FAIL: {type(exc).__name__}; check gateway health and provider configuration")
        return 1
    except AssertionError as exc:
        print(f"FAIL: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
