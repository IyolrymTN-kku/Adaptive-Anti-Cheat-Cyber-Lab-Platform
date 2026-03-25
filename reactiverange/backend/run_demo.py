import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen


def _wait_for_health(base_url: str, server: subprocess.Popen, retries: int = 40, sleep_s: float = 0.5) -> None:
    health_url = f"{base_url}/api/health"
    for _ in range(retries):
        if server.poll() is not None:
            raise RuntimeError(f"Backend exited early with code {server.returncode}.")
        try:
            with urlopen(health_url, timeout=3) as resp:
                if resp.status == 200:
                    return
        except URLError:
            time.sleep(sleep_s)
    raise RuntimeError("Backend did not become healthy in time.")


def _run_step(args, cwd: Path, title: str) -> None:
    print(f"\n==> {title}")
    subprocess.run(args, cwd=str(cwd), check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="ReactiveRange one-shot demo runner")
    parser.add_argument("--base-url", default=os.getenv("SMOKE_BASE_URL", "http://127.0.0.1:5000"))
    parser.add_argument("--email", default=os.getenv("SMOKE_EMAIL", "instructor@reactiverange.local"))
    parser.add_argument("--password", default=os.getenv("SMOKE_PASSWORD", "DemoPass123!"))
    parser.add_argument("--skip-seed", action="store_true", help="Skip seed_data.py")
    args = parser.parse_args()

    backend_dir = Path(__file__).resolve().parent
    python = sys.executable

    server = None
    try:
        if not args.skip_seed:
            _run_step([python, "seed_data.py"], backend_dir, "Seeding demo data")

        print("\n==> Starting backend server")
        server = subprocess.Popen(
            [python, "app.py"],
            cwd=str(backend_dir),
        )

        _wait_for_health(args.base_url, server=server)
        print("Backend healthy.")

        _run_step(
            [
                python,
                "smoke_test.py",
                "--base-url",
                args.base_url,
                "--email",
                args.email,
                "--password",
                args.password,
            ],
            backend_dir,
            "Running smoke test",
        )

        print("\nDemo runner completed successfully.")
        return 0
    except subprocess.CalledProcessError as exc:
        print(f"Command failed with exit code {exc.returncode}: {exc.cmd}")
        return 1
    except Exception as exc:
        print(f"Demo runner failed: {exc}")
        return 1
    finally:
        if server and server.poll() is None:
            print("\n==> Stopping backend server")
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                if os.name == "nt":
                    server.kill()
                else:
                    server.send_signal(signal.SIGKILL)


if __name__ == "__main__":
    raise SystemExit(main())
