import shutil
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user, login_required

from models import Challenge, Scenario, db


scenario_bp = Blueprint("scenario", __name__, url_prefix="/api/scenario")


def _write_scenario_files(scenario_dir: Path, payload: dict) -> None:
    """
    Create the multi-container directory layout and write all generated files:

        scenario_dir/
            docker-compose.yml
            db/
                Dockerfile          ← builds mysql:8.0 image with setup.sql baked in
                setup.sql
            web/
                Dockerfile
                src/
                    index.php

    target-db uses 'build: ./db/' so setup.sql is COPYed into the image at build
    time.  This avoids Docker-out-of-Docker bind-mount issues where the host engine
    cannot resolve paths that only exist inside the backend container.
    """
    # Create only the directories that should be directories.
    (scenario_dir / "db").mkdir(parents=True, exist_ok=True)
    (scenario_dir / "web" / "src").mkdir(parents=True, exist_ok=True)

    # Guard: remove any path that is mistakenly a directory so write_text() succeeds.
    for file_path in [
        scenario_dir / "docker-compose.yml",
        scenario_dir / "db" / "Dockerfile",
        scenario_dir / "db" / "setup.sql",
        scenario_dir / "web" / "Dockerfile",
        scenario_dir / "web" / "src" / "index.php",
    ]:
        if file_path.is_dir():
            shutil.rmtree(file_path)

    (scenario_dir / "docker-compose.yml").write_text(
        payload["docker_compose"], encoding="utf-8"
    )
    # db/Dockerfile bakes setup.sql into the mysql image — no bind mount needed.
    (scenario_dir / "db" / "Dockerfile").write_text(
        payload["db_dockerfile"], encoding="utf-8"
    )
    (scenario_dir / "db" / "setup.sql").write_text(
        payload["setup_sql"], encoding="utf-8"
    )
    (scenario_dir / "web" / "Dockerfile").write_text(
        payload["web_dockerfile"], encoding="utf-8"
    )
    (scenario_dir / "web" / "src" / "index.php").write_text(
        payload["web_source_code"], encoding="utf-8"
    )


@scenario_bp.post("/generate")
@login_required
def generate_scenario():
    if current_user.role != "instructor":
        return jsonify({"error": "Only instructors can generate scenarios"}), 403

    data = request.get_json(force=True)
    vuln_type = data.get("vuln_type")
    difficulty = data.get("difficulty")
    custom_description = data.get("custom_description", "")
    # T_expected: instructor-defined expected solve time in seconds (sent as minutes from UI)
    expected_time = int(data.get("expected_time", 300))
    if expected_time < 30:
        expected_time = 30  # minimum 30 seconds

    if vuln_type not in {"sql_injection", "xss", "cmd_injection"}:
        return jsonify({"error": "Invalid vuln_type"}), 400

    if difficulty not in {"easy", "medium", "hard"}:
        return jsonify({"error": "Invalid difficulty"}), 400

    gemini_service = current_app.extensions["gemini_service"]
    try:
        payload = gemini_service.generate_scenario(vuln_type, difficulty, custom_description)
    except Exception as exc:
        return jsonify({"error": f"Scenario generation failed: {exc}"}), 502

    # --- Persist to DB ---
    # Map multi-container payload fields onto the existing Scenario columns so
    # the rest of the platform (scoreboard, challenge routes) stays unchanged.
    #   dockerfile_content  → docker_compose   (repurposed; preview shows compose file)
    #   rule_json           → detection_rules
    #   challenge_description → description
    #   expected_solution_path → expected_solution
    scenario = Scenario(
        name=f"{vuln_type.replace('_', ' ').title()} ({difficulty.title()})",
        difficulty=difficulty,
        vuln_type=vuln_type,
        dockerfile_content=payload["docker_compose"],
        rule_json=payload["detection_rules"],
        challenge_description=payload["description"],
        expected_solution_path=payload["expected_solution"],
        flag=payload["flag"],
        expected_time=expected_time,
        scenario_dir_path=None,  # filled in after file write below
        created_by=current_user.id,
    )
    db.session.add(scenario)
    db.session.commit()  # commit now to obtain scenario.id

    # --- Write physical files to disk ---
    scenario_dir = Path(current_app.root_path) / "scenarios" / f"scenario_{scenario.id}"
    try:
        _write_scenario_files(scenario_dir, payload)
        scenario.scenario_dir_path = str(scenario_dir)
        db.session.commit()
    except Exception as exc:
        # Non-fatal: scenario record is already saved. Deployment logic
        # (updated in the next step) will check for scenario_dir_path being set.
        print(
            f"[SCENARIO FILES] Warning: failed to write files for scenario {scenario.id}: {exc}"
        )

    # --- API response ---
    # Shape is IDENTICAL to the previous single-Dockerfile response so the
    # React frontend requires zero changes.
    return (
        jsonify(
            {
                "scenario_id": scenario.id,
                "preview": {
                    "name": scenario.name,
                    "difficulty": scenario.difficulty,
                    "vuln_type": scenario.vuln_type,
                    # 'dockerfile_content' now carries the full docker-compose for preview
                    "dockerfile_content": payload["docker_compose"],
                    "rule_json": payload["detection_rules"],
                    "challenge_description": payload["description"],
                    "expected_solution_path": payload["expected_solution"],
                    "flag": payload["flag"],
                    "expected_time": scenario.expected_time,
                },
            }
        ),
        201,
    )


@scenario_bp.get("/list")
@login_required
def list_scenarios():
    scenarios = Scenario.query.order_by(Scenario.id.desc()).all()

    # Fetch all of this user's challenges in one query, then build a lookup:
    #   scenario_id → status of the MOST RECENT challenge (highest .id wins).
    #
    # "Most recent" is determined by challenge.id (auto-increment) rather than
    # started_at to avoid any clock-skew issues.  This guarantees that clicking
    # "Launch Instance" — which creates a NEW challenge row starting as 'active' —
    # immediately clears any old 'solved' badge for that scenario.
    user_challenges = (
        Challenge.query
        .filter_by(team_id=current_user.id)
        .order_by(Challenge.id.desc())          # most-recent first
        .all()
    )
    latest_status: dict[int, str] = {}          # scenario_id → status
    for c in user_challenges:
        if c.scenario_id not in latest_status:  # first occurrence = most recent
            latest_status[c.scenario_id] = c.status

    results = []
    for s in scenarios:
        most_recent_status = latest_status.get(s.id)
        results.append({
            "id": s.id,
            "name": getattr(s, "name", "Unknown"),
            # Frontend uses key 'type' (not 'vuln_type')
            "type": getattr(s, "vuln_type", "other"),
            "difficulty": getattr(s, "difficulty", "unknown"),
            "description": getattr(s, "challenge_description", ""),
            "expected_time": getattr(s, "expected_time", 300),
            "created_at": s.created_at.isoformat() if getattr(s, "created_at", None) else None,
            # True ONLY when this student's most recent challenge for this exact
            # scenario_id has status='solved'.  Any newer 'active' or 'stopped'
            # challenge resets this to False automatically.
            "is_solved": most_recent_status == "solved",
        })

    return jsonify(results), 200


@scenario_bp.delete("/delete/<int:scenario_id>")
@login_required
def delete_scenario(scenario_id):
    if current_user.role != "instructor":
        return jsonify({"error": "Only instructors can delete scenarios"}), 403

    scenario = Scenario.query.get(scenario_id)
    if not scenario:
        return jsonify({"error": "Scenario not found"}), 404

    if scenario.created_by != current_user.id:
        return jsonify({"error": "Forbidden"}), 403

    db.session.delete(scenario)
    db.session.commit()
    return jsonify({"message": "Scenario deleted"}), 200
