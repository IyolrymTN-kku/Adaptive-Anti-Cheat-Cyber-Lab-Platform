import argparse
import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app import create_app
from models import User


def _http_json(method: str, url: str, body=None, headers=None, timeout=15):
    payload = None
    req_headers = {"Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)

    if body is not None:
        payload = json.dumps(body).encode("utf-8")

    req = Request(url=url, data=payload, method=method, headers=req_headers)
    with urlopen(req, timeout=timeout) as resp:
        text = resp.read().decode("utf-8")
        return resp.status, json.loads(text) if text else {}


def _wait_for_health(base_url: str, retries: int = 30, sleep_s: float = 1.0):
    health_url = f"{base_url}/api/health"
    for _ in range(retries):
        try:
            status, data = _http_json("GET", health_url)
            if status == 200 and data.get("status") == "ok":
                return
        except Exception:
            time.sleep(sleep_s)
    raise RuntimeError("Backend health check did not become ready in time.")


def _fetch_latest_otp(email: str) -> str:
    app = create_app()
    with app.app_context():
        user = User.query.filter_by(email=email).first()
        if not user or not user.otp_code:
            raise RuntimeError("OTP code not found in DB after login step.")
        return str(user.otp_code)


def _request(method: str, base_url: str, path: str, body=None, token: str = ""):
    url = f"{base_url}{path}"
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return _http_json(method, url, body=body, headers=headers)


def run_smoke(base_url: str, email: str, password: str):
    print(f"[1/9] Waiting for API health at {base_url} ...")
    _wait_for_health(base_url)
    print("      OK")

    print("[2/9] Login step 1 (request OTP) ...")
    status, data = _request("POST", base_url, "/api/auth/login", {"email": email, "password": password})
    if status != 200 or not data.get("requires_otp"):
        raise RuntimeError(f"Login step 1 failed: {status} {data}")
    print("      OK")

    print("[3/9] Reading OTP from SQLite for smoke flow ...")
    otp = _fetch_latest_otp(email)
    print("      OK")

    print("[4/9] Login step 2 (verify OTP) ...")
    status, data = _request("POST", base_url, "/api/auth/verify-otp", {"email": email, "otp": otp})
    token = data.get("token") if isinstance(data, dict) else None
    if status != 200 or not token:
        raise RuntimeError(f"OTP verify failed: {status} {data}")
    print("      OK")

    print("[5/9] Scenario list ...")
    status, scenarios = _request("GET", base_url, "/api/scenario/list", token=token)
    if status != 200 or not isinstance(scenarios, list):
        raise RuntimeError(f"Scenario list failed: {status} {scenarios}")
    if not scenarios:
        raise RuntimeError("No scenarios found. Run seed_data.py before smoke test.")
    scenario_id = scenarios[0]["id"]
    print(f"      OK (using scenario_id={scenario_id})")

    print("[6/9] Challenge start ...")
    status, started = _request("POST", base_url, "/api/challenge/start", {"scenario_id": scenario_id}, token=token)
    if status != 201:
        raise RuntimeError(f"Challenge start failed: {status} {started}")
    challenge_id = started.get("id")
    if not challenge_id:
        raise RuntimeError("Challenge start did not return challenge id")
    print(f"      OK (challenge_id={challenge_id})")

    print("[7/9] Trigger MTD + read status ...")
    status, decision = _request(
        "POST",
        base_url,
        "/api/challenge/trigger-mtd",
        {"challenge_id": challenge_id, "event_type": "attack_detected"},
        token=token,
    )
    if status != 200 or "action" not in decision:
        raise RuntimeError(f"Trigger MTD failed: {status} {decision}")

    status, challenge_status = _request("GET", base_url, f"/api/challenge/status?challenge_id={challenge_id}", token=token)
    if status != 200 or challenge_status.get("id") != challenge_id:
        raise RuntimeError(f"Challenge status failed: {status} {challenge_status}")
    print(f"      OK (action={decision.get('action')})")

    print("[8/9] Scoreboard live + history ...")
    status, live_scores = _request("GET", base_url, "/api/scores/live", token=token)
    if status != 200 or not isinstance(live_scores, list):
        raise RuntimeError(f"Live scores failed: {status} {live_scores}")

    status, history = _request("GET", base_url, "/api/scores/history", token=token)
    if status != 200 or not isinstance(history, list):
        raise RuntimeError(f"Score history failed: {status} {history}")
    print(f"      OK (live_rows={len(live_scores)}, history_rows={len(history)})")

    print("[9/9] Stop challenge ...")
    status, stopped = _request("POST", base_url, "/api/challenge/stop", {"challenge_id": challenge_id}, token=token)
    if status != 200 or stopped.get("status") != "stopped":
        raise RuntimeError(f"Stop challenge failed: {status} {stopped}")
    print("      OK")

    print("\nSmoke test passed end-to-end.")


def main():
    parser = argparse.ArgumentParser(description="ReactiveRange end-to-end smoke test")
    parser.add_argument("--base-url", default=os.getenv("SMOKE_BASE_URL", "http://127.0.0.1:5000"))
    parser.add_argument("--email", default=os.getenv("SMOKE_EMAIL", "instructor@reactiverange.local"))
    parser.add_argument("--password", default=os.getenv("SMOKE_PASSWORD", "DemoPass123!"))
    args = parser.parse_args()

    try:
        run_smoke(args.base_url, args.email, args.password)
    except (HTTPError, URLError) as net_exc:
        print(f"Network/API error: {net_exc}")
        raise SystemExit(1) from net_exc
    except Exception as exc:
        print(f"Smoke test failed: {exc}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
