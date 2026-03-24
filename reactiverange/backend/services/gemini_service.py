import json
import re

from google import genai


class GeminiService:
    def __init__(self, api_key):
        self.api_key = api_key
        if api_key:
            self.client = genai.Client(api_key=api_key)
            self.model_name = 'gemini-3.1-flash-lite'
        else:
            self.client = None

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

    def generate_scenario(self, vuln_type, difficulty, custom_description=""):
        if not self.client:
            raise RuntimeError("Gemini API key is not configured")

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

        response = self.client.generate_content(prompt)
        payload = self._extract_json(response.text)
        self._validate_payload(payload)
        return payload
