import json
import os
import random
import socket
import subprocess
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import docker
from docker.errors import DockerException

from models import Challenge, Event, Scenario, db
from services.mtd_engine import AdaptiveMTDEngine


class DockerService:
    def __init__(self, socketio=None, app=None):
        self.socketio = socketio
        self.app = app
        self.engines = {}

        base_dir = Path(__file__).resolve().parent
        self.port_lock_dir = base_dir / "port_locks"
        self.state_dir = base_dir / "state"

        self.port_lock_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)

        # Docker SDK client kept for potential diagnostics; primary ops use CLI subprocess.
        self.client = None
        try:
            self.client = docker.from_env()
        except DockerException:
            self.client = None

        self._start_reaper()

    # ------------------------------------------------------------------ events

    def _emit(self, event_type, payload):
        if self.socketio:
            self.socketio.emit("platform_event", {"type": event_type, "payload": payload})

    def _record_event(self, challenge_id, event_type, details):
        event = Event(challenge_id=challenge_id, type=event_type, details=details)
        db.session.add(event)
        db.session.commit()
        self._emit(event_type, {"challenge_id": challenge_id, "details": details})
        return event

    # ------------------------------------------------------------------ state

    def _state_file(self, challenge_id):
        return self.state_dir / f"challenge-{challenge_id}.json"

    def _save_state(self, challenge_id, payload):
        self._state_file(challenge_id).write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )

    def _load_state(self, challenge_id):
        state_file = self._state_file(challenge_id)
        if not state_file.exists():
            return None
        try:
            return json.loads(state_file.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _clear_state(self, challenge_id):
        try:
            self._state_file(challenge_id).unlink(missing_ok=True)
        except Exception:
            pass

    # ------------------------------------------------------------------ ports

    def _is_port_bindable(self, port):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                return False
        return True

    def _reserve_port_lock(self, port):
        lock_file = self.port_lock_dir / f"{port}.lock"
        try:
            fd = os.open(str(lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            return True
        except FileExistsError:
            return False

    def _release_port_lock(self, port):
        if not port:
            return
        lock_file = self.port_lock_dir / f"{port}.lock"
        try:
            lock_file.unlink(missing_ok=True)
        except Exception:
            pass

    def get_free_port(self, min_port=8080, max_port=8999):
        candidates = list(range(min_port, max_port + 1))
        random.shuffle(candidates)
        for port in candidates:
            if not self._is_port_bindable(port):
                continue
            if self._reserve_port_lock(port):
                return port
        raise RuntimeError(f"No free port available in range {min_port}–{max_port}")

    # ------------------------------------------------------------------ compose runner

    def _run_compose_in_dir(self, project_name, scenario_dir, command, extra_env=None):
        """
        Run `docker compose -p <project_name> <command>` with cwd=scenario_dir.
        extra_env values are merged on top of the current process environment so
        that WEB_PORT / VNC_PORT variable substitution in the compose file works.
        """
        env = os.environ.copy()
        if extra_env:
            env.update({k: str(v) for k, v in extra_env.items()})

        cmd = ["docker", "compose", "-p", project_name, *command]
        try:
            result = subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
                cwd=str(scenario_dir),
                env=env,
            )
            return result
        except subprocess.CalledProcessError as exc:
            error_msg = (
                f"docker compose {' '.join(command)} failed "
                f"(project={project_name}, cwd={scenario_dir})\n"
            )
            if exc.stderr:
                error_msg += f"stderr: {exc.stderr}\n"
            if exc.stdout:
                error_msg += f"stdout: {exc.stdout}"
            print(f"[DOCKER COMPOSE ERROR] {error_msg}")
            raise RuntimeError(error_msg) from exc

    # ------------------------------------------------------------------ docker helpers (MTD)

    def _run_docker(self, args, check=True):
        return subprocess.run(["docker", *args], check=check, capture_output=True, text=True)

    def _resolve_service_container(self, project_name, service_name):
        result = self._run_docker(
            [
                "ps", "-q",
                "--filter", f"label=com.docker.compose.project={project_name}",
                "--filter", f"label=com.docker.compose.service={service_name}",
            ],
            check=False,
        )
        container_ids = (result.stdout or "").strip().splitlines()
        return container_ids[0] if container_ids else None

    def _resolve_project_network(self, project_name):
        result = self._run_docker(
            [
                "network", "ls",
                "--filter", f"label=com.docker.compose.project={project_name}",
                "--format", "{{.Name}}",
            ],
            check=False,
        )
        names = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
        if names:
            return names[0]

        for candidate in [
            f"{project_name}_cyber_range_net",
            f"{project_name}_default",
            f"{project_name}-cyber_range_net",
        ]:
            if self._run_docker(["network", "inspect", candidate], check=False).returncode == 0:
                return candidate
        return None

    def _inspect_network_ip(self, container_id, network_name):
        result = self._run_docker(
            [
                "inspect", "-f",
                '{{index .NetworkSettings.Networks "' + network_name + '" "IPAddress"}}',
                container_id,
            ],
            check=False,
        )
        if result.returncode != 0:
            return None
        ip = (result.stdout or "").strip()
        return ip or None

    # ------------------------------------------------------------------ lifecycle

    def start_challenge(self, scenario_id, team_id):
        scenario = Scenario.query.get(scenario_id)
        if not scenario:
            raise ValueError("Scenario not found")

        # Guard: scenario must have been generated with the new multi-container flow.
        if not scenario.scenario_dir_path:
            raise ValueError(
                f"Scenario {scenario_id} has no generated files (scenario_dir_path is not set). "
                "Please ask an instructor to regenerate the scenario."
            )

        scenario_dir = Path(scenario.scenario_dir_path)
        if not scenario_dir.exists():
            raise ValueError(
                f"Scenario directory not found at '{scenario_dir}'. "
                "Please ask an instructor to regenerate the scenario."
            )

        compose_file = scenario_dir / "docker-compose.yml"
        if not compose_file.exists():
            raise ValueError(
                f"docker-compose.yml not found inside '{scenario_dir}'. "
                "Please ask an instructor to regenerate the scenario."
            )

        # Create the Challenge row and commit immediately to release the DB lock
        # before the long-running docker compose build (10-30 s) begins.
        challenge = Challenge(
            name=f"{scenario.name} - Team {team_id}",
            scenario_id=scenario_id,
            status="provisioning",
            container_id=None,
            current_port=None,
            team_id=team_id,
            started_at=datetime.utcnow(),
        )
        db.session.add(challenge)
        db.session.commit()  # full commit so other threads aren't blocked by our lock

        challenge_id = challenge.id
        # Use a namespaced project name to isolate concurrent instances of the same scenario.
        project_name = f"challenge_{challenge_id}"
        vnc_port = None
        web_port = None

        try:
            # Allocate two host ports: one for VNC (Kali NoVNC), one for the web target.
            vnc_port = self.get_free_port(min_port=6901, max_port=6999)
            web_port = self.get_free_port(min_port=8080, max_port=8999)

            print(
                f"[CHALLENGE START] scenario={scenario_id}, project={project_name}, "
                f"vnc_port={vnc_port}, web_port={web_port}, dir={scenario_dir}"
            )

            # Pass ports as environment variables — the compose file uses ${WEB_PORT} / ${VNC_PORT}.
            # DB lock is NOT held during this long-running subprocess call.
            self._run_compose_in_dir(
                project_name,
                scenario_dir,
                ["up", "-d", "--build"],
                extra_env={"WEB_PORT": web_port, "VNC_PORT": vnc_port},
            )

            # Re-query the challenge after the long build to get a fresh session object.
            challenge = Challenge.query.get(challenge_id)
            # current_port stores the VNC port — used by the frontend "Open Kali Console" button.
            challenge.container_id = project_name
            challenge.current_port = vnc_port
            challenge.status = "active"

            self._save_state(
                challenge_id,
                {
                    "project": project_name,
                    "scenario_dir": str(scenario_dir),
                    "vnc_port": vnc_port,
                    "web_port": web_port,
                },
            )
            db.session.commit()

        except Exception as exc:
            # Release reserved ports on any failure.
            if vnc_port:
                self._release_port_lock(vnc_port)
            if web_port:
                self._release_port_lock(web_port)
            # Mark the challenge row as failed so the UI can surface the error.
            try:
                failed_challenge = Challenge.query.get(challenge_id)
                if failed_challenge:
                    failed_challenge.status = "failed"
                    db.session.commit()
            except Exception:
                pass
            msg = f"Failed to start challenge for scenario {scenario_id}: {exc}"
            print(f"[CHALLENGE START ERROR] {msg}")
            raise RuntimeError(msg) from exc

        self.engines[challenge_id] = AdaptiveMTDEngine()
        self._record_event(
            challenge_id,
            "challenge_started",
            {
                "project": project_name,
                "vnc_port": vnc_port,
                "web_port": web_port,
                "scenario_dir": str(scenario_dir),
            },
        )
        return challenge

    def stop_challenge(self, challenge_id):
        challenge = Challenge.query.get(challenge_id)
        if not challenge:
            raise ValueError("Challenge not found")

        state = self._load_state(challenge_id) or {}
        project_name = state.get("project", f"challenge_{challenge_id}")
        scenario_dir_str = state.get("scenario_dir")
        web_port = state.get("web_port")

        # Bring the compose stack down, removing volumes.
        if scenario_dir_str and Path(scenario_dir_str).exists():
            try:
                self._run_compose_in_dir(
                    project_name,
                    Path(scenario_dir_str),
                    ["down", "-v"],
                )
            except Exception as exc:
                # Log but continue — we still want to update DB status.
                print(
                    f"[STOP CHALLENGE] 'docker compose down' failed for challenge "
                    f"{challenge_id} (project={project_name}): {exc}"
                )
        else:
            print(
                f"[STOP CHALLENGE] scenario_dir not found for challenge {challenge_id} "
                f"(state={state}); skipping compose down."
            )

        # Release both port locks.
        self._release_port_lock(challenge.current_port)  # VNC port
        if web_port:
            self._release_port_lock(web_port)

        self._clear_state(challenge_id)

        challenge.status = "stopped"
        db.session.commit()
        self._record_event(challenge_id, "challenge_stopped", {"status": "stopped"})
        return challenge

    def reset_challenge(self, challenge_id):
        challenge = self.stop_challenge(challenge_id)
        scenario = Scenario.query.get(challenge.scenario_id)
        restarted = self.start_challenge(scenario.id, challenge.team_id)
        self._record_event(restarted.id, "challenge_reset", {"from_challenge": challenge_id})
        return restarted

    # ------------------------------------------------------------------ MTD

    def spawn_honeypot(self, challenge_id):
        challenge = Challenge.query.get(challenge_id)
        if not challenge:
            raise ValueError("Challenge not found")

        honeypot_port = min(challenge.current_port + 1, 65535) if challenge.current_port else None
        self._record_event(
            challenge.id,
            "honeypot_hit",
            {"honeypot_port": honeypot_port, "message": "Decoy container spawned."},
        )
        return honeypot_port

    def trigger_mtd_ip_hopping(self, challenge_id):
        challenge = Challenge.query.get(challenge_id)
        if not challenge:
            raise ValueError("Challenge not found")

        # Project name must match what was used when the stack was launched.
        project_name = f"challenge_{challenge.id}"
        network_name = self._resolve_project_network(project_name)
        if not network_name:
            raise RuntimeError(f"No compose network found for challenge {challenge_id}")

        victim_container = self._resolve_service_container(project_name, "target-web")
        if not victim_container:
            raise RuntimeError(
                f"'target-web' container not found for challenge {challenge_id}"
            )

        honeypot_container = self._resolve_service_container(project_name, "attacker-kali")
        if not honeypot_container:
            raise RuntimeError(
                f"'attacker-kali' container not found for challenge {challenge_id}"
            )

        hop_tag = int(time.time())
        self._run_docker(
            ["network", "disconnect", network_name, victim_container], check=False
        )
        self._run_docker(
            ["network", "disconnect", network_name, honeypot_container], check=False
        )
        self._run_docker(
            [
                "network", "connect",
                "--alias", "target-web", "--alias", f"target-web-hop-{hop_tag}",
                network_name, honeypot_container,
            ],
            check=True,
        )
        self._run_docker(
            [
                "network", "connect",
                "--alias", "attacker-kali", "--alias", f"attacker-kali-hop-{hop_tag}",
                network_name, victim_container,
            ],
            check=True,
        )

        victim_new_ip = self._inspect_network_ip(victim_container, network_name)
        honeypot_new_ip = self._inspect_network_ip(honeypot_container, network_name)

        details = {
            "success": True,
            "network": network_name,
            "victim_container": victim_container,
            "honeypot_container": honeypot_container,
            "honeypot_new_ip": honeypot_new_ip,
            "victim_new_ip": victim_new_ip,
            "message": "Swapped target-web and attacker-kali IPs at the network layer",
        }
        self._record_event(challenge_id, "mtd_ip_hop", details)
        return details

    def trigger_mtd(self, challenge_id, event_type="attack_detected"):
        challenge = Challenge.query.get(challenge_id)
        if not challenge:
            raise ValueError("Challenge not found")

        engine = self.engines.get(challenge_id) or AdaptiveMTDEngine()
        self.engines[challenge_id] = engine

        decision = engine.decide_action(event_type)

        if decision.get("action") == "network_ip_hopping":
            hop_details = self.trigger_mtd_ip_hopping(challenge_id)
            decision = {**decision, **hop_details}

        self._record_event(challenge_id, "mtd_triggered", decision)
        return decision

    # ------------------------------------------------------------------ events query

    def get_events(self, challenge_id, limit=100):
        return (
            Event.query.filter_by(challenge_id=challenge_id)
            .order_by(Event.timestamp.desc())
            .limit(limit)
            .all()
        )

    # ------------------------------------------------------------------ background reaper

    def _start_reaper(self):
        # Duration limits by difficulty — must match challenge.py's _DURATION_MAP.
        _DURATION_MAP = {"easy": 15, "medium": 30, "hard": 60}

        def reaper_worker():
            while True:
                time.sleep(60)
                if not self.app:
                    continue
                with self.app.app_context():
                    now = datetime.utcnow()
                    active = Challenge.query.filter_by(status="active").all()
                    for c in active:
                        if not c.started_at:
                            continue
                        try:
                            scenario = Scenario.query.get(c.scenario_id)
                            duration_min = _DURATION_MAP.get(
                                getattr(scenario, "difficulty", "easy"), 15
                            ) if scenario else 15
                            elapsed = (now - c.started_at).total_seconds()
                            if elapsed >= duration_min * 60:
                                self.stop_challenge(c.id)
                                print(
                                    f"[AUTO-TERMINATE] Killed expired Challenge ID: {c.id} "
                                    f"(difficulty={getattr(scenario, 'difficulty', 'unknown')}, "
                                    f"limit={duration_min} min)"
                                )
                        except Exception as exc:
                            print(
                                f"[AUTO-TERMINATE] Error killing Challenge {c.id}: {exc}"
                            )

        reaper_thread = threading.Thread(target=reaper_worker, daemon=True)
        reaper_thread.start()
