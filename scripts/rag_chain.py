"""Provider-specific log classifiers used by the analysis worker pool."""
import os
import json
from dotenv import find_dotenv, load_dotenv
from google import genai
from google.genai import types

load_dotenv(find_dotenv())

SYSTEM_INSTRUCTIONS = """
You are a Site Reliability / Systems Assistant. Classify the supplied live log
entry itself, using retrieved log snippets as supporting context.

Detect whether the entry indicates an anomaly. If it does, identify the error
type, suggest a fix, and provide useful commands. Treat clear failures,
timeouts, connection errors, and critical conditions as anomalies unless the
entry shows they were expected or recovered.

Return only a JSON object with these keys:
- anomaly_detected (true or false)
- error_type (string or "none")
- suggested_fix (string or "none")
- commands (list of strings or [])
- explanation (short reasoning)
- confidence (low, medium, or high)
"""


def _prompt(inputs):
    return f"""LOG ENTRY TO ANALYZE:
{inputs['query']}

RELATED LOG SNIPPETS:
{inputs['context'] or '(No related entries yet; classify the log entry itself.)'}
"""


def get_analyzers():
    """Return configured model workers as {worker_name: (model_id, callable)}.

    Configure ANALYSIS_WORKERS as comma-separated provider/model pairs, for
    example: gemini:gemini-3.8-flash,groq:qwen/qwen3.8-27b,
    nanogpt:openai/gpt-6.1-sol,cloudflare:@cf/cloudflare/clairic,
    requesty:nvidia/nemotron-3.5-lightning-30b-a3b,
    openrouter:recursive/flint-v1.0:free.
    """
    configured = os.getenv(
        "ANALYSIS_WORKERS",
        "gemini:gemini-3.8-flash,groq:qwen/qwen3.8-27b",
    )
    workers = {}
    for item in configured.split(","):
        item = item.strip()
        if not item:
            continue
        provider, separator, model = item.partition(":")
        if not separator or not model.strip():
            raise ValueError(f"Invalid ANALYSIS_WORKERS entry: {item!r}")
        provider, model = provider.strip().lower(), model.strip()
        worker_name = f"{provider}:{model}"

        if provider == "gemini":
            api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
            if not api_key:
                raise RuntimeError("Set GOOGLE_API_KEY to enable the Gemini analysis worker.")
            client = genai.Client(
                api_key=api_key,
                http_options=types.HttpOptions(
                    timeout=60_000,
                    retry_options=types.HttpRetryOptions(attempts=1),
                ),
            )

            def classify_gemini(inputs, client=client, model=model):
                result = client.models.generate_content(
                    model=model,
                    contents=_prompt(inputs),
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_INSTRUCTIONS,
                        response_mime_type="application/json",
                        max_output_tokens=500,
                    ),
                )
                if not result.text:
                    raise RuntimeError("Gemini completed without returning classification text.")
                return result.text

            workers[worker_name] = (model, classify_gemini)
        elif provider == "groq":
            api_key = os.getenv("GROQ_API_KEY")
            if not api_key:
                raise RuntimeError("Set GROQ_API_KEY to enable the Groq analysis worker.")
            from groq import Groq

            client = Groq(api_key=api_key, timeout=60.0, max_retries=0)

            def classify_groq(inputs, client=client, model=model):
                result = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": SYSTEM_INSTRUCTIONS},
                        {"role": "user", "content": _prompt(inputs)},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.2,
                    max_completion_tokens=500,
                )
                content = result.choices[0].message.content
                if not content:
                    raise RuntimeError("Groq completed without returning classification text.")
                return content

            workers[worker_name] = (model, classify_groq)
        elif provider == "nanogpt":
            api_key = os.getenv("NANOGPT_API_KEY")
            if not api_key:
                raise RuntimeError("Set NANOGPT_API_KEY to enable the NanoGPT analysis worker.")
            from openai import OpenAI

            client = OpenAI(
                api_key=api_key,
                base_url=os.getenv("NANOGPT_BASE_URL", "https://nano-gpt.com/api/v1"),
                timeout=60.0,
                max_retries=0,
            )

            def classify_nanogpt(inputs, client=client, model=model):
                result = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": SYSTEM_INSTRUCTIONS + " Return valid JSON only; do not use Markdown."},
                        {"role": "user", "content": _prompt(inputs)},
                    ],
                    temperature=0.2,
                    max_tokens=500,
                )
                content = result.choices[0].message.content
                if not content:
                    raise RuntimeError("NanoGPT completed without returning classification text.")
                return content

            workers[worker_name] = (model, classify_nanogpt)
        elif provider == "requesty":
            api_key = os.getenv("REQUESTY_API_KEY")
            if not api_key:
                raise RuntimeError("Set REQUESTY_API_KEY to enable the Requesty analysis worker.")
            from openai import OpenAI

            client = OpenAI(
                api_key=api_key,
                base_url=os.getenv("REQUESTY_BASE_URL", "https://router.requesty.ai/v1"),
                timeout=60.0,
                max_retries=0,
            )

            def classify_requesty(inputs, client=client, model=model):
                result = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": SYSTEM_INSTRUCTIONS + " Return valid JSON only; do not use Markdown."},
                        {"role": "user", "content": _prompt(inputs)},
                    ],
                    temperature=0.2,
                    max_tokens=500,
                )
                content = result.choices[0].message.content
                if not content:
                    raise RuntimeError("Requesty completed without returning classification text.")
                return content

            workers[worker_name] = (model, classify_requesty)
        elif provider == "openrouter":
            api_key = os.getenv("OPENROUTER_API_KEY")
            if not api_key:
                raise RuntimeError("Set OPENROUTER_API_KEY to enable the OpenRouter analysis worker.")
            from openai import OpenAI

            client = OpenAI(
                api_key=api_key,
                base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
                timeout=60.0,
                max_retries=0,
            )

            def classify_openrouter(inputs, client=client, model=model):
                result = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": SYSTEM_INSTRUCTIONS + " Return valid JSON only; do not use Markdown."},
                        {"role": "user", "content": _prompt(inputs)},
                    ],
                    temperature=0.2,
                    max_tokens=500,
                )
                content = result.choices[0].message.content
                if not content:
                    raise RuntimeError("OpenRouter completed without returning classification text.")
                return content

            workers[worker_name] = (model, classify_openrouter)
        elif provider == "cloudflare":
            account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID")
            api_token = os.getenv("CLOUDFLARE_AUTH_TOKEN")
            if not account_id or not api_token:
                raise RuntimeError(
                    "Set CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_AUTH_TOKEN to enable Cloudflare Workers AI."
                )
            import requests

            def classify_cloudflare(inputs, model=model, account_id=account_id, api_token=api_token):
                state = inputs.get("state") or inputs["query"]
                url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}"
                response = requests.post(
                    url,
                    headers={"Authorization": f"Bearer {api_token}"},
                    json={
                        "model": "clairic",
                        "state": state,
                        "fields": {
                            "severity": {
                                "type": "text",
                                "instructions": "Extract the exact log severity level if present, such as ERROR, WARN, INFO, FATAL, or CRITICAL.",
                            },
                            "error_type": {
                                "type": "text",
                                "instructions": "Extract the exact exception or error type explicitly named in the log.",
                            },
                            "error_code": {
                                "type": "text",
                                "instructions": "Extract an explicit error code or identifier from the log, if present.",
                            },
                        },
                    },
                    timeout=60,
                )
                response.raise_for_status()
                payload = response.json()
                if payload.get("success") is False or payload.get("errors"):
                    raise RuntimeError(f"Cloudflare Workers AI error: {payload.get('errors')}")
                result = payload.get("result", payload)
                answers = result.get("answers", {})

                def answer_value(name):
                    answer = answers.get(name) or {}
                    return answer.get("value") or answer.get("guess")

                severity = answer_value("severity")
                error_type = answer_value("error_type")
                error_code = answer_value("error_code")
                severity_text = str(severity or "").upper()
                is_anomaly = bool(
                    severity_text in {"ERROR", "FATAL", "CRITICAL", "PANIC", "ALERT", "EMERGENCY", "WARN", "WARNING"}
                    or error_type
                    or error_code
                )
                confidence_values = [
                    answer.get("confidence")
                    for answer in answers.values()
                    if isinstance(answer, dict) and isinstance(answer.get("confidence"), (int, float))
                ]
                confidence = min(confidence_values) if confidence_values else 0
                extracted = ", ".join(
                    f"{name}={value}" for name, value in (
                        ("severity", severity), ("error_type", error_type), ("error_code", error_code)
                    ) if value
                )
                needs_review = not extracted or confidence < 0.6
                return json.dumps({
                    "anomaly_detected": is_anomaly,
                    "error_type": error_type or ("log_error" if is_anomaly else "none"),
                    "suggested_fix": "Clairic extracts structured fields but does not generate remediation advice.",
                    "commands": [],
                    "explanation": (
                        f"Clairic extracted {extracted}. Confidence: {confidence:.2f}."
                        if extracted else "Clairic found no explicit severity or error fields; manual review is needed."
                    ),
                    "confidence": "high" if confidence >= 0.85 else "medium" if confidence >= 0.6 else "low",
                    "needs_review": needs_review,
                })

            workers[worker_name] = (model, classify_cloudflare)
        else:
            raise ValueError(
                f"Unsupported analysis provider {provider!r}; use gemini, groq, nanogpt, requesty, openrouter, or cloudflare."
            )

    if not workers:
        raise RuntimeError("ANALYSIS_WORKERS must configure at least one model worker.")
    return workers
