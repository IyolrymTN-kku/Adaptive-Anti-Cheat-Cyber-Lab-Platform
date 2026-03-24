from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user, login_required

from models import Challenge, Scenario
from services.scoring_service import ScoringService


challenge_bp = Blueprint("challenge", __name__, url_prefix="/api/challenge")


@challenge_bp.post("/start")
@login_required
def start_challenge():
    data = request.get_json(force=True)
    scenario_id = data.get("scenario_id")
    team_id = data.get("team_id") or current_user.id

    if current_user.role != "instructor" and int(team_id) != current_user.id:
        return jsonify({"error": "Students can only start their own team challenge"}), 403

    scenario = Scenario.query.get(scenario_id)
    if not scenario:
        return jsonify({"error": "Scenario not found"}), 404

    docker_service = current_app.extensions["docker_service"]
    challenge = docker_service.start_challenge(scenario_id, team_id)

    return (
        jsonify(
            {
                "id": challenge.id,
                "status": challenge.status,
                "port": challenge.current_port,
                "container_id": challenge.container_id,
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
        return (
            jsonify(
                {
                    "id": challenge.id,
                    "status": challenge.status,
                    "port": challenge.current_port,
                    "scenario_id": challenge.scenario_id,
                    "team_id": challenge.team_id,
                    "started_at": challenge.started_at.isoformat() if challenge.started_at else None,
                }
            ),
            200,
        )

    query = Challenge.query
    if current_user.role != "instructor":
        query = query.filter_by(team_id=current_user.id)

    results = [
        {
            "id": c.id,
            "status": c.status,
            "port": c.current_port,
            "scenario_id": c.scenario_id,
            "team_id": c.team_id,
            "started_at": c.started_at.isoformat() if c.started_at else None,
        }
        for c in query.order_by(Challenge.id.desc()).all()
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
        user_id=restarted.team_id,
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

    scorer = ScoringService()
    scorer.update_score(
        user_id=challenge.team_id,
        challenge_id=challenge.id,
        base_delta=15,
        deception_penalty_delta=max(0, (decision["penalty_multiplier"] - 1.0) * 10),
        mtd_evasions_delta=1,
    )

    return jsonify(decision), 200
