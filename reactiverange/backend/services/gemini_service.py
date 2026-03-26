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
        import base64
        
        # 1. สร้าง Flag ของจริงเตรียมไว้ให้ขโมย
        flag_val = f"FLAG{{{vuln_type}_{difficulty}_training_success}}"
        setup_cmd = ""

        # 2. เขียนโค้ดเว็บที่มีช่องโหว่ของจริงตามหมวดหมู่ (ต้องชิดซ้ายสุด ห้ามมีย่อหน้า!)
        if vuln_type == "cmd_injection":
            app_code = f"""from flask import Flask, request
import subprocess
app = Flask(__name__)
@app.route('/')
def index():
    return '<h2>Network Ping Tool</h2><form action="/ping"><input name="ip" value="127.0.0.1"><button type="submit">Ping</button></form><p>Hint: Read /flag.txt</p>'
@app.route('/ping')
def ping():
    ip = request.args.get('ip', '')
    try:
        out = subprocess.check_output("ping -c 1 " + ip, shell=True, text=True)
    except Exception as e:
        out = str(e)
    return '<pre>' + out + '</pre><br><a href="/">Back</a>'
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)"""
            setup_cmd = f"RUN echo '{flag_val}' > /flag.txt"

        elif vuln_type == "sql_injection":
            app_code = f"""from flask import Flask, request
import sqlite3
app = Flask(__name__)
def init_db():
    conn = sqlite3.connect('test.db')
    conn.execute('CREATE TABLE IF NOT EXISTS users (username TEXT, password TEXT)')
    conn.execute("INSERT INTO users VALUES ('admin', 'supersecret_password')")
    conn.commit()
    conn.close()
init_db()
@app.route('/')
def index():
    return '<h2>Admin Portal Login</h2><form action="/login">Username: <input name="user"><br>Password: <input type="password" name="pass"><br><button type="submit">Login</button></form>'
@app.route('/login')
def login():
    u = request.args.get('user', '')
    p = request.args.get('pass', '')
    conn = sqlite3.connect('test.db')
    cur = conn.cursor()
    query = f"SELECT * FROM users WHERE username='{{u}}' AND password='{{p}}'"
    try:
        cur.execute(query)
        if cur.fetchone():
            return '<h1>Welcome Admin!</h1><p>Your secret flag is: {flag_val}</p>'
        else:
            return 'Invalid credentials. <a href="/">Try again</a>'
    except Exception as e:
        return 'SQL Error: ' + str(e)
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)"""

        else: # XSS หรืออื่นๆ
            app_code = f"""from flask import Flask, request
app = Flask(__name__)
@app.route('/')
def index():
    name = request.args.get('name', 'Guest')
    return '<h2>Welcome ' + name + '</h2><form action="/"><input name="name" placeholder="Enter your name"><button type="submit">Submit</button></form>'
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)"""

        # แปลงเป็น Base64
        app_b64 = base64.b64encode(app_code.encode('utf-8')).decode('utf-8')

        dockerfile = (
            "FROM python:3.11-slim\n"
            "WORKDIR /app\n"
            "RUN pip install flask\n"
            f"{setup_cmd}\n"
            f"RUN echo '{app_b64}' | base64 -d > app.py\n"
            "EXPOSE 5000\n"
            "CMD [\"python\", \"app.py\"]\n"
        )

        return {
            "dockerfile_content": dockerfile,
            "rule_json": [r"(?i)(attack|payload|exploit)"],
            "challenge_description": f"Target deployed. Analyze and exploit the {vuln_type} vulnerability to extract the flag.",
            "expected_solution_path": "Analyze source, craft payload, exploit vulnerability, submit flag.",
            "flag": flag_val,
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
            "dockerfile_content (string, complete Dockerfile. IMPORTANT: Do NOT use 'COPY . .'. You MUST write the vulnerable python/php code entirely inline using 'RUN echo \"...code...\" > app.py' inside the Dockerfile), "
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
