import json
import re
import textwrap

try:
    from google import genai
except Exception:
    genai = None

try:
    import google.generativeai as legacy_genai
except Exception:
    legacy_genai = None


_REQUIRED_KEYS = [
    "docker_compose",
    "db_dockerfile",
    "setup_sql",
    "web_dockerfile",
    "web_source_code",
    "detection_rules",
    "description",
    "expected_solution",
    "flag",
]


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
        for key in _REQUIRED_KEYS:
            if key not in payload:
                raise ValueError(f"Gemini response missing required key '{key}'")

        compose = payload["docker_compose"]
        for required_service in ("target-db", "target-web", "attacker-kali"):
            if required_service not in compose:
                raise ValueError(
                    f"docker_compose must define service '{required_service}'"
                )

        if not isinstance(payload["detection_rules"], (list, dict)):
            raise ValueError("detection_rules must be a list or object")

        if not str(payload["flag"]).startswith("FLAG{"):
            raise ValueError("flag must start with 'FLAG{'")

    @staticmethod
    def _build_offline_payload(vuln_type, difficulty, custom_description="", reason=""):
        """
        Returns a fully offline multi-container payload matching the same 8-key schema
        that Gemini is expected to return. Used when the API is unavailable.
        """
        flag_val = f"FLAG{{{vuln_type}_{difficulty}_training_success}}"

        # docker-compose is the same template for all vuln types.
        # ${WEB_PORT} and ${VNC_PORT} are docker-compose variable substitutions
        # that the deployment logic will inject at runtime.
        # target-db uses build: ./db/ so setup.sql is baked into the image.
        # This avoids bind-mount DooD issues when the backend runs inside a container
        # and Docker on the host can't resolve paths that only exist inside the backend.
        docker_compose = textwrap.dedent("""\
            version: '3.8'
            services:
              target-db:
                build: ./db/
                environment:
                  MYSQL_ROOT_PASSWORD: rootpass
                  MYSQL_DATABASE: ctfdb
                networks:
                  - cyber_range_net

              target-web:
                build: ./web/
                ports:
                  - "${WEB_PORT:-8080}:80"
                depends_on:
                  - target-db
                networks:
                  - cyber_range_net

              attacker-kali:
                image: kasmweb/kali-rolling-desktop:1.14.0
                environment:
                  VNC_PW: password
                ports:
                  - "${VNC_PORT:-6901}:6901"
                shm_size: 512m
                networks:
                  - cyber_range_net

            networks:
              cyber_range_net:
                driver: bridge
        """)

        if vuln_type == "sql_injection":
            setup_sql = textwrap.dedent(f"""\
                CREATE DATABASE IF NOT EXISTS ctfdb;
                USE ctfdb;
                CREATE TABLE IF NOT EXISTS users (
                    id       INT AUTO_INCREMENT PRIMARY KEY,
                    username VARCHAR(50)  NOT NULL,
                    password VARCHAR(50)  NOT NULL,
                    notes    VARCHAR(200)
                );
                INSERT INTO users (username, password, notes) VALUES
                    ('admin', 'supersecret', '{flag_val}'),
                    ('alice', 'alice123',    'regular user'),
                    ('bob',   'bob456',      'regular user');
            """)

            web_dockerfile = textwrap.dedent("""\
                FROM php:8.1-apache
                RUN docker-php-ext-install pdo pdo_mysql
                COPY src/ /var/www/html/
                EXPOSE 80
            """)

            web_source_code = textwrap.dedent("""\
                <?php
                $dsn      = 'mysql:host=target-db;dbname=ctfdb;charset=utf8';
                $pdo_opts = [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION];
                $username = $_GET['username'] ?? '';
                $password = $_GET['password'] ?? '';
                $message  = '';

                if ($username !== '' && $password !== '') {
                    try {
                        $pdo = new PDO($dsn, 'root', 'rootpass', $pdo_opts);
                        // VULNERABLE: Direct string interpolation — SQL Injection is possible
                        $sql  = "SELECT * FROM users WHERE username='$username' AND password='$password'";
                        $stmt = $pdo->query($sql);
                        $row  = $stmt->fetch(PDO::FETCH_ASSOC);
                        if ($row) {
                            $message = '<p style="color:green">Welcome '
                                     . htmlspecialchars($row['username'])
                                     . '! Secret: ' . $row['notes'] . '</p>';
                        } else {
                            $message = '<p style="color:red">Invalid credentials.</p>';
                        }
                    } catch (PDOException $e) {
                        $message = '<p style="color:orange">DB Error: ' . $e->getMessage() . '</p>';
                    }
                }
                ?>
                <!DOCTYPE html>
                <html><head><title>Admin Login</title></head><body>
                <h2>Admin Portal</h2>
                <form method="GET">
                  Username: <input name="username" value="<?= htmlspecialchars($username) ?>"><br><br>
                  Password: <input type="password" name="password"><br><br>
                  <button type="submit">Login</button>
                </form>
                <?= $message ?>
                </body></html>
            """)

            detection_rules = [
                r"(?i)('\s*(or|and)\s*'?[\d])",
                r"(?i)(union\s+select)",
                r"(?i)(--\s|#\s*$)",
                r"(?i)(\bor\b\s+\d+\s*=\s*\d+)",
            ]
            description = (
                "An internal admin portal is exposed on port 80. Analysts suspect the login form "
                "is vulnerable to SQL Injection. Retrieve the secret stored in the database to get the flag."
            )
            expected_solution = (
                "1. Open the login form. "
                "2. Inject a tautology into the username field, e.g. ' OR '1'='1 with any password. "
                "3. The raw query returns all rows; the first row's 'notes' column contains the flag."
            )

        elif vuln_type == "cmd_injection":
            # For cmd_injection the flag lives on the container filesystem (/flag.txt),
            # not in the DB — the web Dockerfile writes it there.
            setup_sql = textwrap.dedent("""\
                CREATE DATABASE IF NOT EXISTS ctfdb;
                USE ctfdb;
                CREATE TABLE IF NOT EXISTS info (
                    id   INT AUTO_INCREMENT PRIMARY KEY,
                    note TEXT
                );
                INSERT INTO info (note) VALUES ('System monitoring initialized.');
            """)

            web_dockerfile = textwrap.dedent(f"""\
                FROM php:8.1-apache
                RUN apt-get update && apt-get install -y iputils-ping \\
                    && rm -rf /var/lib/apt/lists/*
                RUN docker-php-ext-install pdo pdo_mysql
                RUN echo '{flag_val}' > /flag.txt
                COPY src/ /var/www/html/
                EXPOSE 80
            """)

            web_source_code = textwrap.dedent("""\
                <?php
                $output = '';
                $ip     = $_GET['ip'] ?? '';

                if ($ip !== '') {
                    // VULNERABLE: Unsanitised $ip passed directly to shell_exec
                    $output = shell_exec('ping -c 2 ' . $ip . ' 2>&1');
                }
                ?>
                <!DOCTYPE html>
                <html><head><title>Network Diagnostics</title></head><body>
                <h2>Network Ping Utility</h2>
                <form method="GET">
                  Target IP / Host:
                  <input name="ip" value="<?= htmlspecialchars($ip) ?>" size="30">
                  <button type="submit">Ping</button>
                </form>
                <?php if ($output !== ''): ?>
                <pre><?= htmlspecialchars($output) ?></pre>
                <?php endif; ?>
                <p><small>Hint: Sensitive files may exist on the server filesystem.</small></p>
                </body></html>
            """)

            detection_rules = [
                r"(?i)(;\s*(cat|ls|id|whoami|uname|wget|curl)\b)",
                r"(?i)(\|\s*\w+)",
                r"(?i)(`[^`]+`)",
                r"(?i)(\$\([^)]+\))",
            ]
            description = (
                "A network diagnostic tool on port 80 allows administrators to ping hosts. "
                "The IP input is not sanitised. Inject OS commands to read the flag from the server filesystem."
            )
            expected_solution = (
                "1. Open the ping tool. "
                "2. Enter a payload like: 127.0.0.1; cat /flag.txt "
                "3. The shell executes both ping and your injected command, revealing the flag."
            )

        else:  # xss
            setup_sql = textwrap.dedent(f"""\
                CREATE DATABASE IF NOT EXISTS ctfdb;
                USE ctfdb;
                CREATE TABLE IF NOT EXISTS comments (
                    id      INT AUTO_INCREMENT PRIMARY KEY,
                    author  VARCHAR(50),
                    content TEXT
                );
                CREATE TABLE IF NOT EXISTS secrets (
                    id   INT AUTO_INCREMENT PRIMARY KEY,
                    flag VARCHAR(200)
                );
                INSERT INTO comments (author, content)
                    VALUES ('admin', 'Welcome to the community feedback board!');
                INSERT INTO secrets (flag) VALUES ('{flag_val}');
            """)

            web_dockerfile = textwrap.dedent("""\
                FROM php:8.1-apache
                RUN docker-php-ext-install pdo pdo_mysql
                COPY src/ /var/www/html/
                EXPOSE 80
            """)

            web_source_code = textwrap.dedent("""\
                <?php
                $dsn      = 'mysql:host=target-db;dbname=ctfdb;charset=utf8';
                $pdo_opts = [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION];

                if ($_SERVER['REQUEST_METHOD'] === 'POST'
                        && !empty($_POST['author'])
                        && !empty($_POST['content'])) {
                    try {
                        $pdo = new PDO($dsn, 'root', 'rootpass', $pdo_opts);
                        $pdo->prepare("INSERT INTO comments (author, content) VALUES (?, ?)")
                            ->execute([$_POST['author'], $_POST['content']]);
                    } catch (PDOException $e) { /* silent */ }
                    header('Location: /');
                    exit;
                }

                $comments  = [];
                $flag_val  = '';
                try {
                    $pdo      = new PDO($dsn, 'root', 'rootpass', $pdo_opts);
                    $comments = $pdo->query("SELECT * FROM comments ORDER BY id DESC")
                                    ->fetchAll(PDO::FETCH_ASSOC);
                    $row      = $pdo->query("SELECT flag FROM secrets LIMIT 1")->fetch();
                    if ($row) { $flag_val = $row['flag']; }
                } catch (PDOException $e) { /* silent */ }
                ?>
                <!DOCTYPE html>
                <html>
                <head><title>Feedback Board</title>
                <script>
                // The admin bot that reviews comments has this session cookie:
                document.cookie = "admin_token=<?= htmlspecialchars($flag_val, ENT_QUOTES) ?>; path=/";
                </script>
                </head>
                <body>
                <h2>Community Feedback Board</h2>
                <form method="POST">
                  Name: <input name="author"><br>
                  Comment: <textarea name="content" rows="3" cols="40"></textarea><br>
                  <button type="submit">Post</button>
                </form>
                <hr><h3>Recent Comments:</h3>
                <?php foreach ($comments as $c): ?>
                <div style="border:1px solid #ccc;margin:5px;padding:8px;">
                  <b><?= htmlspecialchars($c['author']) ?></b>:
                  <?= $c['content'] /* VULNERABLE: No htmlspecialchars — Stored XSS */ ?>
                </div>
                <?php endforeach; ?>
                </body></html>
            """)

            detection_rules = [
                r"(?i)(<script[^>]*>)",
                r"(?i)(onerror\s*=)",
                r"(?i)(javascript\s*:)",
                r"(?i)(on(load|click|mouseover)\s*=)",
            ]
            description = (
                "A community feedback board on port 80 stores comments without sanitisation. "
                "The admin's session cookie contains the flag. "
                "Inject a stored XSS payload to steal it."
            )
            expected_solution = (
                "1. Post a comment with a <script> payload that reads document.cookie. "
                "2. Exfiltrate it via fetch() or an <img> onerror to the Kali attacker container. "
                "3. The admin_token cookie value is the flag."
            )

        db_dockerfile = textwrap.dedent("""\
            FROM mysql:8.0
            COPY setup.sql /docker-entrypoint-initdb.d/
        """)

        return {
            "docker_compose":    docker_compose,
            "db_dockerfile":     db_dockerfile,
            "setup_sql":         setup_sql,
            "web_dockerfile":    web_dockerfile,
            "web_source_code":   web_source_code,
            "detection_rules":   detection_rules,
            "description":       description,
            "expected_solution": expected_solution,
            "flag":              flag_val,
        }

    @staticmethod
    def _is_model_not_found_error(err_text):
        text = (err_text or "").lower()
        return "not_found" in text or ("model" in text and "not found" in text)

    @staticmethod
    def _is_quota_or_rate_limit_error(err_text):
        text = (err_text or "").lower()
        return (
            "resource_exhausted" in text
            or "quota exceeded" in text
            or "rate limit" in text
            or ("429" in text and "quota" in text)
        )

    def generate_scenario(self, vuln_type, difficulty, custom_description=""):
        """
        Calls Gemini to generate a full multi-container CTF scenario.

        Returns a dict with 8 keys:
            docker_compose, setup_sql, web_dockerfile, web_source_code,
            detection_rules, description, expected_solution, flag

        Falls back to _build_offline_payload() when the Gemini API is
        unavailable, invalid, or quota-exhausted.
        """
        if not self.client and not self.legacy_model:
            return self._build_offline_payload(
                vuln_type, difficulty, custom_description,
                reason="Gemini API key is not configured",
            )

        prompt = (
            f"You are a CTF challenge architect. Generate a realistic multi-container web hacking "
            f"challenge for vulnerability type '{vuln_type}' at '{difficulty}' difficulty.\n\n"
            "Return ONLY a single valid JSON object with EXACTLY these 9 keys. "
            "No markdown, no code fences, no extra text — just the raw JSON.\n\n"

            "1. \"docker_compose\": (string) Complete docker-compose.yml with 3 services:\n"
            "   - 'target-db': MUST use 'build: ./db/' — do NOT use 'image: mysql:8.0' directly "
            "     and do NOT add any 'volumes' entry for target-db. "
            "     Environment: MYSQL_ROOT_PASSWORD=rootpass, MYSQL_DATABASE=ctfdb.\n"
            "   - 'target-web': build context ./web/. "
            "     Ports: ${WEB_PORT:-8080}:80. depends_on: [target-db].\n"
            "   - 'attacker-kali': image kasmweb/kali-rolling-desktop:1.14.0. "
            "     Environment: VNC_PW=password. "
            "     Ports: ${VNC_PORT:-6901}:6901. shm_size: 512m.\n"
            "   All 3 services share a bridge network named 'cyber_range_net'.\n\n"

            "2. \"db_dockerfile\": (string) Dockerfile for target-db. "
            "   It must look EXACTLY like this (no changes):\n"
            "     FROM mysql:8.0\n"
            "     COPY setup.sql /docker-entrypoint-initdb.d/\n"
            "   This bakes setup.sql into the image to avoid bind-mount issues.\n\n"

            "3. \"setup_sql\": (string) SQL to CREATE the ctfdb schema/tables and INSERT the flag "
            "   into a table row. This file will be COPYed into the image by db_dockerfile.\n\n"

            "4. \"web_dockerfile\": (string) Dockerfile for target-web. "
            "   Base: php:8.1-apache. "
            "   Must run docker-php-ext-install pdo pdo_mysql. "
            "   Must COPY src/ to /var/www/html/. "
            "   For cmd_injection: also apt-get install iputils-ping and write flag to /flag.txt.\n\n"

            "5. \"web_source_code\": (string) Full index.php. "
            "   Must connect to target-db via PDO (host=target-db, user=root, pass=rootpass, db=ctfdb). "
            f"  Must contain a genuinely exploitable {vuln_type} vulnerability.\n\n"

            "6. \"detection_rules\": (array of strings) At least 3 regex patterns matching "
            f"  common {vuln_type} attack payloads.\n\n"

            "7. \"description\": (string) Challenge description shown to the student.\n\n"

            "8. \"expected_solution\": (string) Step-by-step solution guide for the instructor.\n\n"

            "9. \"flag\": (string) Format FLAG{...}. "
            "   This exact string MUST also appear in setup_sql as an INSERT value "
            "   (or in web_dockerfile for cmd_injection).\n\n"

            "CRITICAL: All JSON string values must be properly escaped. "
            "The vulnerability must be genuinely exploitable, not cosmetic."
        )

        if custom_description:
            prompt += f"\n\nExtra requirements: {custom_description}"

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
            err_text = " ".join([str(new_sdk_error or ""), str(legacy_error or "")]).strip()

            if "API key not valid" in err_text or "API_KEY_INVALID" in err_text:
                return self._build_offline_payload(
                    vuln_type, difficulty, custom_description, reason="invalid Gemini API key"
                )
            if self._is_model_not_found_error(err_text):
                return self._build_offline_payload(
                    vuln_type, difficulty, custom_description, reason="Gemini model unavailable"
                )
            if self._is_quota_or_rate_limit_error(err_text):
                return self._build_offline_payload(
                    vuln_type, difficulty, custom_description, reason="Gemini quota exhausted"
                )
            if new_sdk_error is not None or legacy_error is not None:
                raise RuntimeError(
                    f"Gemini SDK invocation failed: {err_text or 'unknown generation error'}"
                )
            return self._build_offline_payload(
                vuln_type, difficulty, custom_description, reason="Unsupported Gemini client methods"
            )

        response_text = self._extract_response_text(response)
        if not response_text:
            raise RuntimeError("Gemini returned an empty response")

        payload = self._extract_json(response_text)
        self._validate_payload(payload)
        return payload
