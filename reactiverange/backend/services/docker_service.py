import io
import json
import os
import random
import socket
import subprocess
import tarfile
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
        self.template_dir = base_dir / "templates"
        self.temp_dir = base_dir / "tmp"
        self.port_lock_dir = base_dir / "port_locks"
        self.state_dir = base_dir / "state"

        self.template_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.port_lock_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)

        self.client = None
        try:
            self.client = docker.from_env()
        except DockerException:
            self.client = None

        self._start_reaper()

    def _emit(self, event_type, payload):
        if self.socketio:
            self.socketio.emit("platform_event", {"type": event_type, "payload": payload})

    def _record_event(self, challenge_id, event_type, details):
        event = Event(challenge_id=challenge_id, type=event_type, details=details)
        db.session.add(event)
        db.session.commit()
        self._emit(event_type, {"challenge_id": challenge_id, "details": details})
        return event

    def _state_file(self, challenge_id):
        return self.state_dir / f"challenge-{challenge_id}.json"

    def _compose_file(self, challenge_id):
        return self.temp_dir / f"docker-compose-{challenge_id}.yml"

    def _save_state(self, challenge_id, payload):
        self._state_file(challenge_id).write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
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

    def get_free_port(self, min_port=5901, max_port=5999):
        candidates = list(range(min_port, max_port + 1))
        random.shuffle(candidates)
        for port in candidates:
            if not self._is_port_bindable(port):
                continue
            if self._reserve_port_lock(port):
                return port
        raise RuntimeError("No free VNC port available")

    def _run_compose(self, challenge_id, compose_file, command):
        cmd = [
            "docker",
            "compose",
            "-p",
            str(challenge_id),
            "-f",
            str(compose_file),
            *command,
        ]
        try:
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            return result
        except subprocess.CalledProcessError as e:
            error_msg = f"docker compose command failed: {' '.join(cmd)}\n"
            if e.stderr:
                error_msg += f"stderr: {e.stderr}\n"
            if e.stdout:
                error_msg += f"stdout: {e.stdout}"
            print(f"[DOCKER COMPOSE ERROR] {error_msg}")
            raise RuntimeError(error_msg) from e

    def _run_docker(self, args, check=True):
        return subprocess.run(["docker", *args], check=check, capture_output=True, text=True)

    def _resolve_service_container(self, project_name, service_name):
        result = self._run_docker(
            [
                "ps",
                "-q",
                "--filter",
                f"label=com.docker.compose.project={project_name}",
                "--filter",
                f"label=com.docker.compose.service={service_name}",
            ],
            check=False,
        )
        container_id = (result.stdout or "").strip().splitlines()
        return container_id[0] if container_id else None

    def _resolve_project_network(self, project_name):
        result = self._run_docker(
            [
                "network",
                "ls",
                "--filter",
                f"label=com.docker.compose.project={project_name}",
                "--format",
                "{{.Name}}",
            ],
            check=False,
        )
        names = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
        if names:
            return names[0]

        preferred_names = [
            f"{project_name}_cyber_range_net",
            f"{project_name}_default",
            f"{project_name}-cyber_range_net",
        ]
        for name in preferred_names:
            inspect = self._run_docker(["network", "inspect", name], check=False)
            if inspect.returncode == 0:
                return name
        return None

    def _inspect_network_ip(self, container_id, network_name):
        result = self._run_docker(
            [
                "inspect",
                "-f",
                "{{index .NetworkSettings.Networks \"" + network_name + "\" \"IPAddress\"}}",
                container_id,
            ],
            check=False,
        )
        if result.returncode != 0:
            return None
        ip = (result.stdout or "").strip()
        return ip or None

    def _build_image_from_scenario(self, scenario: Scenario):
        if not self.client:
            raise RuntimeError("Docker daemon is unavailable for image build")

        dockerfile_bytes = scenario.dockerfile_content.encode("utf-8")
        image_tag = f"reactiverange/scenario-{scenario.id}:latest"
        
        # Create a tar archive with the Dockerfile
        tar_buffer = io.BytesIO()
        tar = tarfile.open(fileobj=tar_buffer, mode="w")
        
        dockerfile_tarinfo = tarfile.TarInfo(name="Dockerfile")
        dockerfile_tarinfo.size = len(dockerfile_bytes)
        tar.addfile(dockerfile_tarinfo, io.BytesIO(dockerfile_bytes))
  
        tar.close()
        
        tar_buffer.seek(0)
        self.client.images.build(
            fileobj=tar_buffer,
            custom_context=True,
            tag=image_tag,
            rm=True,
            pull=False,
        )
        return image_tag

    def start_challenge(self, scenario_id, team_id):
        scenario = Scenario.query.get(scenario_id)
        if not scenario:
            raise ValueError("Scenario not found")

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
        db.session.flush()

        vnc_port = None
        compose_file = self._compose_file(challenge.id)

        try:
            image_tag = self._build_image_from_scenario(scenario)
            vnc_port = self.get_free_port()

            template_path = self.template_dir / "base_topology.yml"
            if not template_path.exists():
                raise FileNotFoundError(
                    f"Topology template not found at {template_path}. "
                    f"Please create {template_path} with docker compose service definitions for Kali, victim, and honeypot."
                )

            compose_content = template_path.read_text(encoding="utf-8")
            compose_content = compose_content.replace("${VNC_PORT}", str(vnc_port))
            compose_content = compose_content.replace("${VULN_IMAGE}", image_tag)

            print(f"[DOCKER SERVICE] Generated compose file for challenge {challenge.id}:")
            print(f"[DOCKER SERVICE] === Compose Content ===\n{compose_content}\n=== End ===")

            compose_file.write_text(compose_content, encoding="utf-8")

            self._run_compose(challenge.id, compose_file, ["up", "-d"])

            challenge.container_id = f"compose-{challenge.id}"
            challenge.current_port = vnc_port
            challenge.status = "active"

            self._save_state(
                challenge.id,
                {
                    "project": str(challenge.id),
                    "compose_file": str(compose_file),
                    "vnc_port": vnc_port,
                    "image_tag": image_tag,
                },
            )
            db.session.commit()
        except Exception as e:
            if vnc_port:
                self._release_port_lock(vnc_port)
            try:
                compose_file.unlink(missing_ok=True)
            except Exception:
                pass
            db.session.rollback()
            error_context = f"Failed to start challenge for scenario {scenario_id}: {str(e)}"
            print(f"[CHALLENGE START ERROR] {error_context}")
            raise RuntimeError(error_context) from e

        self.engines[challenge.id] = AdaptiveMTDEngine()
        self._record_event(
            challenge.id,
            "challenge_started",
            {
                "vnc_port": challenge.current_port,
                "container_id": challenge.container_id,
                "compose_file": str(compose_file),
            },
        )

        return challenge

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

        project_name = str(challenge.id)
        network_name = self._resolve_project_network(project_name)
        if not network_name:
            raise RuntimeError(f"No compose network found for challenge {challenge_id}")

        victim_container = self._resolve_service_container(project_name, "victim")
        if not victim_container:
            raise RuntimeError(f"Victim container not found for challenge {challenge_id}")

        honeypot_container = self._resolve_service_container(project_name, "honeypot")
        if not honeypot_container:
            raise RuntimeError(f"Honeypot container not found for challenge {challenge_id}")

        hop_tag = int(time.time())
        victim_alias = f"victim-hop-{hop_tag}"
        honeypot_alias = f"honeypot-hop-{hop_tag}"

        self._run_docker(["network", "disconnect", network_name, victim_container], check=False)
        self._run_docker(["network", "disconnect", network_name, honeypot_container], check=False)

        self._run_docker(
            ["network", "connect", "--alias", "victim", "--alias", victim_alias, network_name, honeypot_container],
            check=True,
        )
        self._run_docker(
            ["network", "connect", "--alias", "honeypot", "--alias", honeypot_alias, network_name, victim_container],
            check=True,
        )

        victim_new_ip = self._inspect_network_ip(victim_container, network_name)
        honeypot_new_ip = self._inspect_network_ip(honeypot_container, network_name)

        details = {
            "success": True,
            "network": network_name,
            "victim_container": victim_container,
            "honeypot_container": honeypot_container,
            "victim_new_ip": victim_new_ip,
            "honeypot_new_ip": honeypot_new_ip,
            "message": "Swapped Victim and Honeypot IPs at the network layer",
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

    def stop_challenge(self, challenge_id):
        challenge = Challenge.query.get(challenge_id)
        if not challenge:
            raise ValueError("Challenge not found")

        state = self._load_state(challenge_id) or {}
        compose_file = Path(state.get("compose_file", str(self._compose_file(challenge_id))))

        try:
            if compose_file.exists():
                self._run_compose(challenge_id, compose_file, ["down", "-v"])
        except Exception:
            pass

        self._release_port_lock(challenge.current_port)

        try:
            compose_file.unlink(missing_ok=True)
        except Exception:
            pass
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

    def get_events(self, challenge_id, limit=100):
        return (
            Event.query.filter_by(challenge_id=challenge_id)
            .order_by(Event.timestamp.desc())
            .limit(limit)
            .all()
        )

    def _start_reaper(self):
        def reaper_worker():
            while True:
                time.sleep(60)  # ตื่นมาตรวจทุกๆ 1 นาที
                if not self.app:
                    continue
                    
                with self.app.app_context():
                    # กำหนดเวลาหมดอายุ (15 นาที)
                    cutoff_time = datetime.utcnow() - timedelta(minutes=15)
                    
                    # ค้นหาโจทย์ที่ Active และเวลาเริ่มเก่ากว่า 15 นาที
                    expired_challenges = Challenge.query.filter(
                        Challenge.status == "active",
                        Challenge.started_at <= cutoff_time
                    ).all()
                    
                    for c in expired_challenges:
                        try:
                            # สั่ง Terminate คอนเทนเนอร์ที่หมดอายุ
                            self.stop_challenge(c.id)
                            print(f"[AUTO-TERMINATE] Killed expired Challenge ID: {c.id} (Exceeded 15 mins)")
                        except Exception as e:
                            print(f"[AUTO-TERMINATE] Error killing Challenge {c.id}: {e}")

        # สั่งรันแบบ Background Thread (ถ้าระบบหลักปิด ยมทูตก็จะตายตามไปด้วย)
        reaper_thread = threading.Thread(target=reaper_worker, daemon=True)
        reaper_thread.start()
