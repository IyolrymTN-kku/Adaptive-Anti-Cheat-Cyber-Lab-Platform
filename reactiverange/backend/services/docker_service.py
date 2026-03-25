import io
import random
import tarfile
import threading
import time
from datetime import datetime

import docker
from docker.errors import DockerException

from models import Challenge, Event, Scenario, db
from services.mtd_engine import AdaptiveMTDEngine

from datetime import datetime, timedelta


class DockerService:
    def __init__(self, socketio=None, app=None):
        self.socketio = socketio
        self.app = app
        self.engines = {}
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

    def _build_image_from_scenario(self, scenario: Scenario):
        if not self.client:
            return None

        dockerfile_bytes = scenario.dockerfile_content.encode("utf-8")
        image_tag = f"reactiverange/scenario-{scenario.id}:latest"
        
        # Create a tar archive with the Dockerfile
        tar_buffer = io.BytesIO()
        tar = tarfile.open(fileobj=tar_buffer, mode="w")
        
        dockerfile_tarinfo = tarfile.TarInfo(name="Dockerfile")
        dockerfile_tarinfo.size = len(dockerfile_bytes)
        tar.addfile(dockerfile_tarinfo, io.BytesIO(dockerfile_bytes))


        default_app_code = (
            "from flask import Flask\n"
            "app = Flask(__name__)\n"
            "@app.route('/')\n"
            "def index(): return 'Cyber Range Target is Active!'\n"
            "if __name__ == '__main__': app.run(host='0.0.0.0', port=5000)\n"
        )
        app_bytes = default_app_code.encode("utf-8")
        app_tarinfo = tarfile.TarInfo(name="app.py")
        app_tarinfo.size = len(app_bytes)
        tar.addfile(app_tarinfo, io.BytesIO(app_bytes))
        
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

    def _run_container(self, image_tag, port):
        if not self.client:
            return None
        container = self.client.containers.run(
            image_tag,
            detach=True,
            ports={"5000/tcp": port},
            auto_remove=True,
            name=f"reactiverange-{int(time.time())}-{random.randint(1000, 9999)}",
        )
        return container

    def _monitor_logs(self, challenge_id, container):
        if not self.client or not container:
            return

        def _worker():
            try:
                for line in container.logs(stream=True, follow=True):
                    content = line.decode("utf-8", errors="ignore").strip()
                    if not content:
                        continue
                    
                    # Use app context for database operations
                    if self.app:
                        with self.app.app_context():
                            self._record_event(
                                challenge_id,
                                "attack_detected" if "attack" in content.lower() else "system_log",
                                {"log": content},
                            )
                    else:
                        # If no app context, just emit without recording to DB
                        self._emit(
                            "attack_detected" if "attack" in content.lower() else "system_log",
                            {"challenge_id": challenge_id, "log": content},
                        )
            except Exception as exc:
                if self.app:
                    with self.app.app_context():
                        self._record_event(challenge_id, "system_log", {"error": str(exc)})
                else:
                    self._emit("system_log", {"challenge_id": challenge_id, "error": str(exc)})

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()

    def start_challenge(self, scenario_id, team_id):
        scenario = Scenario.query.get(scenario_id)
        if not scenario:
            raise ValueError("Scenario not found")

        port = random.randint(1024, 65535)
        image_tag = None
        container = None

        if self.client:
            image_tag = self._build_image_from_scenario(scenario)
            container = self._run_container(image_tag, port)

        challenge = Challenge(
            name=f"{scenario.name} - Team {team_id}",
            scenario_id=scenario_id,
            status="active",
            container_id=container.id if container else "simulated-container",
            current_port=port,
            team_id=team_id,
            started_at=datetime.utcnow(),
        )
        db.session.add(challenge)
        db.session.commit()

        self.engines[challenge.id] = AdaptiveMTDEngine()
        self._record_event(
            challenge.id,
            "challenge_started",
            {"port": port, "container_id": challenge.container_id},
        )

        if container:
            self._monitor_logs(challenge.id, container)

        return challenge

    def _restart_container(self, challenge, new_port):
        if not self.client:
            challenge.current_port = new_port
            db.session.commit()
            return

        scenario = Scenario.query.get(challenge.scenario_id)
        image_tag = f"reactiverange/scenario-{scenario.id}:latest"

        if challenge.container_id:
            try:
                old_container = self.client.containers.get(challenge.container_id)
                old_container.kill(signal="SIGKILL")
            except Exception:
                pass

        new_container = self._run_container(image_tag, new_port)
        challenge.container_id = new_container.id
        challenge.current_port = new_port
        db.session.commit()
        self._monitor_logs(challenge.id, new_container)

    def spawn_honeypot(self, challenge_id):
        challenge = Challenge.query.get(challenge_id)
        if not challenge:
            raise ValueError("Challenge not found")

        honeypot_port = min(challenge.current_port + 1, 65535) if challenge.current_port else random.randint(1024, 65535)

        if self.client:
            scenario = Scenario.query.get(challenge.scenario_id)
            image_tag = f"reactiverange/scenario-{scenario.id}:latest"
            try:
                self._run_container(image_tag, honeypot_port)
            except Exception:
                pass

        self._record_event(
            challenge.id,
            "honeypot_hit",
            {"honeypot_port": honeypot_port, "message": "Decoy container spawned."},
        )
        return honeypot_port

    def trigger_mtd(self, challenge_id, event_type="attack_detected"):
        challenge = Challenge.query.get(challenge_id)
        if not challenge:
            raise ValueError("Challenge not found")

        engine = self.engines.get(challenge_id) or AdaptiveMTDEngine()
        self.engines[challenge_id] = engine

        decision = engine.decide_action(event_type)

        if decision["action"] == "port_migrate" and decision["new_port"]:
            self._restart_container(challenge, decision["new_port"])
        elif decision["action"] in {"add_honeypot", "honeypot_swarm"}:
            self.spawn_honeypot(challenge_id)

        self._record_event(challenge_id, "mtd_triggered", decision)
        return decision

    def stop_challenge(self, challenge_id):
        challenge = Challenge.query.get(challenge_id)
        if not challenge:
            raise ValueError("Challenge not found")

        if self.client and challenge.container_id:
            try:
                container = self.client.containers.get(challenge.container_id)
                container.kill(signal="SIGKILL")
            except Exception:
                pass

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
                            print(f"[AUTO-TERMINATE] 💀 Killed expired Challenge ID: {c.id} (Exceeded 15 mins)")
                        except Exception as e:
                            print(f"[AUTO-TERMINATE] Error killing Challenge {c.id}: {e}")

        # สั่งรันแบบ Background Thread (ถ้าระบบหลักปิด ยมทูตก็จะตายตามไปด้วย)
        reaper_thread = threading.Thread(target=reaper_worker, daemon=True)
        reaper_thread.start()
