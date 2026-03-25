from datetime import datetime, timedelta

import bcrypt

from app import create_app
from models import Challenge, Event, Scenario, Score, Session, User, db


def _hash_password(raw_password: str) -> str:
    return bcrypt.hashpw(raw_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _upsert_user(email: str, username: str, role: str, password: str) -> User:
    user = User.query.filter_by(email=email).first()
    if user:
        user.username = username
        user.role = role
        if not user.password_hash:
            user.password_hash = _hash_password(password)
        return user

    user = User(
        email=email,
        username=username,
        role=role,
        password_hash=_hash_password(password),
        mfa_verified=True,
    )
    db.session.add(user)
    return user


def _upsert_scenario(name: str, difficulty: str, vuln_type: str, created_by: int) -> Scenario:
    scenario = Scenario.query.filter_by(name=name, created_by=created_by).first()
    dockerfile = (
        "FROM python:3.11-slim\n"
        "WORKDIR /app\n"
        "COPY . .\n"
        "RUN pip install flask\n"
        "EXPOSE 5000\n"
        "CMD [\"python\", \"app.py\"]\n"
    )
    rule_json = [r"(?i)(union\\s+select|or\\s+1=1)", r"(?i)(<script>|onerror=)"]

    if scenario:
        scenario.difficulty = difficulty
        scenario.vuln_type = vuln_type
        scenario.dockerfile_content = dockerfile
        scenario.rule_json = rule_json
        scenario.challenge_description = "Seeded demo scenario for smoke and UI verification."
        scenario.expected_solution_path = "Use payload-based probing and recover the seeded FLAG value."
        scenario.flag = "FLAG{reactiverange_seed_demo}"
        return scenario

    scenario = Scenario(
        name=name,
        difficulty=difficulty,
        vuln_type=vuln_type,
        dockerfile_content=dockerfile,
        rule_json=rule_json,
        challenge_description="Seeded demo scenario for smoke and UI verification.",
        expected_solution_path="Use payload-based probing and recover the seeded FLAG value.",
        flag="FLAG{reactiverange_seed_demo}",
        created_by=created_by,
    )
    db.session.add(scenario)
    return scenario


def _upsert_challenge(scenario_id: int, team_id: int) -> Challenge:
    challenge = Challenge.query.filter_by(scenario_id=scenario_id, team_id=team_id).first()
    if challenge:
        challenge.name = f"Seed Challenge Team {team_id}"
        challenge.status = "active"
        challenge.current_port = challenge.current_port or 43210
        challenge.container_id = challenge.container_id or "seeded-container"
        challenge.started_at = challenge.started_at or datetime.utcnow() - timedelta(minutes=10)
        return challenge

    challenge = Challenge(
        name=f"Seed Challenge Team {team_id}",
        scenario_id=scenario_id,
        status="active",
        container_id="seeded-container",
        current_port=43210,
        team_id=team_id,
        started_at=datetime.utcnow() - timedelta(minutes=10),
    )
    db.session.add(challenge)
    return challenge


def _upsert_score(user_id: int, challenge_id: int, base_score: float, penalty: float, solved: int, hits: int, evasions: int):
    score = Score.query.filter_by(user_id=user_id, challenge_id=challenge_id).first()
    net = max(base_score - penalty, 0)
    if score:
        score.base_score = base_score
        score.speed_multiplier = 1.0
        score.deception_penalty = penalty
        score.net_score = net
        score.solved = solved
        score.deception_hits = hits
        score.mtd_evasions = evasions
        score.last_activity = datetime.utcnow()
        return score

    score = Score(
        user_id=user_id,
        challenge_id=challenge_id,
        base_score=base_score,
        speed_multiplier=1.0,
        deception_penalty=penalty,
        net_score=net,
        solved=solved,
        deception_hits=hits,
        mtd_evasions=evasions,
        last_activity=datetime.utcnow(),
    )
    db.session.add(score)
    return score


def _ensure_session(user_id: int, challenge_id: int):
    session_row = Session.query.filter_by(user_id=user_id, challenge_id=challenge_id, status="active").first()
    if session_row:
        return session_row

    session_row = Session(user_id=user_id, challenge_id=challenge_id, status="active")
    db.session.add(session_row)
    return session_row


def _seed_event(challenge_id: int, event_type: str, details: dict):
    event = Event(challenge_id=challenge_id, type=event_type, details=details)
    db.session.add(event)


def run_seed():
    app = create_app()
    with app.app_context():
        db.create_all()

        instructor = _upsert_user(
            email="instructor@reactiverange.local",
            username="instructor_demo",
            role="instructor",
            password="DemoPass123!",
        )
        student = _upsert_user(
            email="student@reactiverange.local",
            username="student_demo",
            role="student",
            password="DemoPass123!",
        )
        db.session.commit()

        scenario = _upsert_scenario(
            name="Seed SQL Intro",
            difficulty="easy",
            vuln_type="sql_injection",
            created_by=instructor.id,
        )
        db.session.commit()

        challenge = _upsert_challenge(scenario_id=scenario.id, team_id=student.id)
        db.session.commit()

        _upsert_score(student.id, challenge.id, base_score=180, penalty=35, solved=2, hits=1, evasions=3)
        _ensure_session(student.id, challenge.id)

        _seed_event(challenge.id, "attack_detected", {"source_ip": "10.10.10.25", "payload": "' OR 1=1 --"})
        _seed_event(challenge.id, "mtd_triggered", {"action": "port_migrate", "new_port": 43210})
        _seed_event(challenge.id, "honeypot_hit", {"honeypot_port": 43211})
        _seed_event(challenge.id, "score_update", {"user_id": student.id, "net_score": 145})

        db.session.commit()

        print("Seed complete.")
        print("Instructor login: instructor@reactiverange.local / DemoPass123!")
        print("Student login: student@reactiverange.local / DemoPass123!")
        print(f"Seed scenario id: {scenario.id}")
        print(f"Seed challenge id: {challenge.id}")


if __name__ == "__main__":
    run_seed()
