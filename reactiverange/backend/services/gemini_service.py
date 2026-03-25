import json
import re

try:
    from google import genai
except Exception:
    genai = None

try:
    import google.generativeai as legacy_genai
except Exception:
    legacy_genai = None


class GeminiService:
    def __init__(self, api_key):
        self.api_key = api_key
        self.client = None
        self.legacy_model = None
        self.model_name = "gemini-1.5-flash"
        self.model_candidates = [
            self.model_name,
            "gemini-1.5-flash-latest",
            "gemini-1.5-flash-8b",
            "gemini-1.5-pro",
            "gemini-2.0-flash",
            "gemini-2.0-flash-lite",
        ]

        if api_key:
            if genai is not None:
                try:
                    self.client = genai.Client(api_key=api_key)
                except Exception:
                    self.client = None

            if legacy_genai is not None:
                try:
                    legacy_genai.configure(api_key=api_key)
                    self.legacy_model = legacy_genai.GenerativeModel(self.model_name)
                except Exception:
                    self.legacy_model = None

    @staticmethod
    def _extract_response_text(response):
        # Support multiple Gemini SDK response shapes.
        for attr in ("text", "output_text"):
            value = getattr(response, attr, None)
            if value:
                return value

        candidates = getattr(response, "candidates", None)
        if candidates:
            for candidate in candidates:
                content = getattr(candidate, "content", None)
                parts = getattr(content, "parts", None) if content else None
                if not parts:
                    continue
                texts = [getattr(part, "text", "") for part in parts]
                joined = "".join(texts).strip()
                if joined:
                    return joined

        return None

    def _call_new_sdk(self, prompt, model_name):
        if self.client is None:
            return None

        models_api = getattr(self.client, "models", None)
        if models_api is not None and hasattr(models_api, "generate_content"):
            return models_api.generate_content(model=model_name, contents=prompt)

        if hasattr(self.client, "generate_content"):
            return self.client.generate_content(model=model_name, contents=prompt)

        return None

    @staticmethod
    def _extract_json(raw_text: str):
        cleaned = raw_text.strip()
        fence_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", cleaned, re.DOTALL)
        if fence_match:
            cleaned = fence_match.group(1)
        return json.loads(cleaned)

    @staticmethod
    def _validate_payload(payload):
        required = [
            "dockerfile_content",
            "rule_json",
            "challenge_description",
            "expected_solution_path",
            "flag",
        ]
        for key in required:
            if key not in payload:
                raise ValueError(f"Gemini response missing '{key}'")

        dockerfile = payload["dockerfile_content"]
        if "FROM" not in dockerfile.upper() or "EXPOSE" not in dockerfile.upper():
            raise ValueError("Generated Dockerfile must include FROM and EXPOSE")

        if not isinstance(payload["rule_json"], list):
            raise ValueError("rule_json must be an array of regex patterns")

    @staticmethod
    def _build_offline_payload(vuln_type, difficulty, custom_description="", reason=""):
        rule_map = {
            "sql_injection": [
                r"(?i)(\bUNION\b|\bSELECT\b|\bOR\b\s+1=1)",
                r"(?i)(--|#|/\*)",
            ],
            "xss": [
                r"(?i)<\s*script",
                r"(?i)onerror\s*=|onload\s*=|javascript:",
            ],
            "cmd_injection": [
                r"(;|&&|\|\|)",
                r"(?i)(\bcurl\b|\bwget\b|\bcat\b\s+/etc/passwd)",
            ],
        }

        vuln_titles = {
            "sql_injection": "SQL Injection",
            "xss": "Cross-Site Scripting (XSS)",
            "cmd_injection": "Command Injection",
        }

        difficulty_hint = {
            "easy": "single-step exploit",
            "medium": "two-step exploit with basic filtering",
            "hard": "multi-step exploit with noisy defenses",
        }

        desc_suffix = f" Extra requirement: {custom_description}." if custom_description else ""
        reason_suffix = f" [Fallback mode: {reason}]" if reason else ""

        return {
            "dockerfile_content": (
                "FROM python:3.11-slim\n"
                "WORKDIR /app\n"
                "RUN pip install flask\n"
                "COPY . .\n"
                "EXPOSE 5000\n"
                "CMD [\"python\", \"app.py\"]\n"
            ),
            "rule_json": rule_map.get(vuln_type, [r"(?i)(attack|payload|exploit)"]),
            "challenge_description": (
                f"Exploit a {vuln_titles.get(vuln_type, vuln_type)} vulnerability "
                f"at {difficulty} difficulty ({difficulty_hint.get(difficulty, 'guided exploit')})."
                f" Retrieve the flag from the vulnerable service.{desc_suffix}{reason_suffix}"
            ),
            "expected_solution_path": (
                f"Craft a {vuln_type} payload, bypass basic checks, and exfiltrate FLAG{{...}} from server response."
            ),
            "flag": f"FLAG{{{vuln_type}_{difficulty}_training}}",
        }

    @staticmethod
    def _is_model_not_found_error(err_text):
        text = (err_text or "").lower()
        return "not_found" in text or "model" in text and "not found" in text

    @staticmethod
    def _is_quota_or_rate_limit_error(err_text):
        text = (err_text or "").lower()
        return (
            "resource_exhausted" in text
            or "quota exceeded" in text
            or "rate limit" in text
            or "429" in text and "quota" in text
        )

    def generate_scenario(self, vuln_type, difficulty, custom_description=""):
        if not self.client and not self.legacy_model:
            return self._build_offline_payload(
                vuln_type,
                difficulty,
                custom_description,
                reason="Gemini API key is not configured",
            )

        prompt = (
            f"Generate a CTF challenge for {vuln_type} at {difficulty} level. "
            "Return ONLY valid JSON with keys: "
            "dockerfile_content (string, complete Dockerfile for vulnerable Flask/PHP app), "
            "rule_json (array of regex patterns that match attack payloads), "
            "challenge_description (string, shown to student), "
            "expected_solution_path (string, instructor-only hint), "
            "flag (string, format FLAG{...}). "
        )

        if custom_description:
            prompt += f"Blend in this extra scenario requirement: {custom_description}."

        response = None
        new_sdk_error = None
        legacy_error = None

        if self.client is not None:
            for model_name in self.model_candidates:
                try:
                    response = self._call_new_sdk(prompt, model_name)
                    if response is not None:
                        break
                except Exception as exc:
                    new_sdk_error = exc
                    if not self._is_model_not_found_error(str(exc)):
                        break

        if response is None and self.legacy_model is not None:
            for model_name in self.model_candidates:
                try:
                    model = legacy_genai.GenerativeModel(model_name)
                    response = model.generate_content(prompt)
                    if response is not None:
                        break
                except Exception as exc:
                    legacy_error = exc
                    if not self._is_model_not_found_error(str(exc)):
                        break

        if response is None:
            err_text = " ".join(
                [
                    str(new_sdk_error or ""),
                    str(legacy_error or ""),
                ]
            ).strip()

            if "API key not valid" in err_text or "API_KEY_INVALID" in err_text:
                return self._build_offline_payload(
                    vuln_type,
                    difficulty,
                    custom_description,
                    reason="invalid Gemini API key",
                )

            if self._is_model_not_found_error(err_text):
                return self._build_offline_payload(
                    vuln_type,
                    difficulty,
                    custom_description,
                    reason="Gemini model unavailable",
                )

            if self._is_quota_or_rate_limit_error(err_text):
                return self._build_offline_payload(
                    vuln_type,
                    difficulty,
                    custom_description,
                    reason="Gemini quota exhausted",
                )

            if new_sdk_error is not None or legacy_error is not None:
                raise RuntimeError(
                    f"Gemini SDK invocation failed: {err_text or 'unknown generation error'}"
                )

            return self._build_offline_payload(
                vuln_type,
                difficulty,
                custom_description,
                reason="Unsupported Gemini client methods",
            )

        response_text = self._extract_response_text(response)
        if not response_text:
            raise RuntimeError("Gemini returned an empty response")

        payload = self._extract_json(response_text)
        self._validate_payload(payload)
        return payload
