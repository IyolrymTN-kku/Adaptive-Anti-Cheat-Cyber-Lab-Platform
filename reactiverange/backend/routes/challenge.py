from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user, login_required

from models import Challenge, Scenario, User
from services.scoring_service import ScoringService


challenge_bp = Blueprint("challenge", __name__, url_prefix="/api/challenge")

# Instance duration by scenario difficulty (minutes).
_DURATION_MAP = {"easy": 15, "medium": 30, "hard": 60}


def _duration_for(scenario):
    """Return the instance duration in minutes for the given Scenario object."""
    return _DURATION_MAP.get(getattr(scenario, "difficulty", "easy"), 15)


@challenge_bp.post("/start")
@login_required
def start_challenge():
    data = request.get_json(force=True)
    scenario_id = data.get("scenario_id")

    scenario = Scenario.query.get(scenario_id)
    if not scenario:
        return jsonify({"error": "Scenario not found"}), 404

    # Scenarios generated before the multi-container refactor won't have files on disk.
    if not scenario.scenario_dir_path:
        return jsonify({
            "error": (
                "This scenario was generated before the multi-container upgrade. "
                "Please ask an instructor to regenerate it."
            )
        }), 422

    docker_service = current_app.extensions["docker_service"]
    try:
        challenge = docker_service.start_challenge(scenario_id, current_user.id)
    except ValueError as exc:
        # Configuration problems (missing dir, missing compose file, etc.)
        return jsonify({"error": str(exc)}), 422
    except RuntimeError as exc:
        # Docker/subprocess failures
        return jsonify({"error": f"Failed to launch instance: {exc}"}), 500

    scenario = Scenario.query.get(scenario_id)
    return (
        jsonify(
            {
                "id": challenge.id,
                "status": challenge.status,
                # current_port = VNC port — used by "Open Kali Linux Console" button
                "port": challenge.current_port,
                "container_id": challenge.container_id,
                "duration_minutes": _duration_for(scenario),
            }
        ),
        201,
    )


@challenge_bp.post("/stop")
@login_required
def stop_challenge():
    data = request.get_json(force=True)
    challenge_id = data.get("challenge_id")

    challenge = Challenge.query.get(challenge_id)
    if not challenge:
        return jsonify({"error": "Challenge not found"}), 404

    if current_user.role != "instructor" and challenge.team_id != current_user.id:
        return jsonify({"error": "Forbidden"}), 403

    docker_service = current_app.extensions["docker_service"]
    updated = docker_service.stop_challenge(challenge_id)

    if current_user.role == "instructor":
        active_student_challenges = Challenge.query.filter_by(
            scenario_id=challenge.scenario_id,
            status="active"
        ).all()
        for sc in active_student_challenges:
            if sc.id != challenge_id:
                docker_service.stop_challenge(sc.id)

    return jsonify({"id": updated.id, "status": updated.status}), 200


@challenge_bp.get("/status")
@login_required
def status_challenge():
    challenge_id = request.args.get("challenge_id", type=int)

    if challenge_id:
        challenge = Challenge.query.get(challenge_id)
        if not challenge:
            return jsonify({"error": "Challenge not found"}), 404
        if current_user.role != "instructor" and challenge.team_id != current_user.id:
            return jsonify({"error": "Forbidden"}), 403
        scenario = Scenario.query.get(challenge.scenario_id)
        return (
            jsonify(
                {
                    "id": challenge.id,
                    "status": challenge.status,
                    "port": challenge.current_port,
                    "scenario_id": challenge.scenario_id,
                    "team_id": challenge.team_id,
                    "started_at": challenge.started_at.isoformat() if challenge.started_at else None,
                    "duration_minutes": _duration_for(scenario),
                }
            ),
            200,
        )

    # Return all challenges for this user (instructors see everyone's).
    query = Challenge.query
    if current_user.role != "instructor":
        query = query.filter_by(team_id=current_user.id)

    challenges = query.order_by(Challenge.id.desc()).all()

    # Bulk-load scenarios to avoid N+1 queries.
    scenario_ids = list({c.scenario_id for c in challenges})
    scenarios_by_id = (
        {s.id: s for s in Scenario.query.filter(Scenario.id.in_(scenario_ids)).all()}
        if scenario_ids else {}
    )

    results = [
        {
            "id": c.id,
            "status": c.status,
            "port": c.current_port,
            "scenario_id": c.scenario_id,
            "team_id": c.team_id,
            "started_at": c.started_at.isoformat() if c.started_at else None,
            "duration_minutes": _duration_for(scenarios_by_id.get(c.scenario_id)),
        }
        for c in challenges
    ]
    return jsonify(results), 200


@challenge_bp.post("/reset")
@login_required
def reset_challenge():
    data = request.get_json(force=True)
    challenge_id = data.get("challenge_id")

    challenge = Challenge.query.get(challenge_id)
    if not challenge:
        return jsonify({"error": "Challenge not found"}), 404

    if current_user.role != "instructor" and challenge.team_id != current_user.id:
        return jsonify({"error": "Forbidden"}), 403

    docker_service = current_app.extensions["docker_service"]
    restarted = docker_service.reset_challenge(challenge_id)

    scorer = ScoringService()
    scorer.update_score(
        user_id=current_user.id,
        challenge_id=restarted.id,
        base_delta=-10,
        deception_penalty_delta=5,
        deception_hits_delta=1,
    )

    return jsonify({"id": restarted.id, "status": restarted.status, "port": restarted.current_port}), 200


@challenge_bp.post("/trigger-mtd")
@login_required
def trigger_mtd():
    data = request.get_json(force=True)
    challenge_id = data.get("challenge_id")
    event_type = data.get("event_type", "attack_detected")

    challenge = Challenge.query.get(challenge_id)
    if not challenge:
        return jsonify({"error": "Challenge not found"}), 404

    if current_user.role != "instructor" and challenge.team_id != current_user.id:
        return jsonify({"error": "Forbidden"}), 403

    docker_service = current_app.extensions["docker_service"]
    decision = docker_service.trigger_mtd(challenge_id, event_type=event_type)

    penalty_mult = decision.get("penalty_multiplier", 1.0)

    scorer = ScoringService()
    scorer.update_score(
        user_id=current_user.id,
        challenge_id=challenge.id,
        base_delta=15,
        deception_penalty_delta=max(0, (penalty_mult - 1.0) * 10),
        mtd_evasions_delta=1,
    )

    return jsonify(decision), 200

@challenge_bp.post("/submit")
@login_required
def submit_flag():
    from datetime import datetime
    from models import Event, db

    data = request.get_json(force=True)
    challenge_id = data.get("challenge_id")
    # Accept "answer" (new terminology) with "flag" as a fallback for any old clients.
    submitted_flag = (data.get("answer") or data.get("flag", "")).strip()

    challenge = Challenge.query.get(challenge_id)
    if not challenge:
        return jsonify({"error": "Challenge not found"}), 404

    scenario = Scenario.query.get(challenge.scenario_id)
    if not scenario:
        return jsonify({"error": "Scenario not found"}), 404

    if scenario.flag == submitted_flag:
        if challenge.status == "solved":
            return jsonify({"success": True, "message": "You already solved this challenge!"}), 200

        # Actual time elapsed since challenge started (seconds)
        t_actual = (
            (datetime.utcnow() - challenge.started_at).total_seconds()
            if challenge.started_at
            else 300.0
        )

        # Calculate score using the paper formula:
        # S = max(0, min(W_a × (T_expected / T_actual) − W_p × E_trap, 2 × W_a))
        scorer = ScoringService()
        score_entry = scorer.record_solve(
            user_id=current_user.id,
            challenge_id=challenge.id,
            difficulty=scenario.difficulty,
            t_actual=t_actual,
            t_expected=getattr(scenario, "expected_time", None),
        )

        solve_event = Event(
            challenge_id=challenge.id,
            type="score_update",
            details={
                "message": "Flag captured successfully!",
                "points_added": score_entry.net_score,
            },
        )
        db.session.add(solve_event)
        db.session.commit()

        docker_service = current_app.extensions.get("docker_service")
        if docker_service:
            try:
                docker_service._emit("score_update", {"challenge_id": challenge.id, "points": score_entry.net_score})
                docker_service.stop_challenge(challenge.id)
            except Exception as e:
                print(f"Cleanup error: {e}")

        challenge.status = "solved"
        db.session.commit()

        return jsonify({"success": True, "message": f"Correct Answer! +{round(score_entry.net_score)} Points!"}), 200
    else:
        return jsonify({"success": False, "message": "Incorrect Answer, please try again."}), 200