from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user, login_required

from models import Challenge, Scenario, User
from services.scoring_service import ScoringService



challenge_bp = Blueprint("challenge", __name__, url_prefix="/api/challenge")


@challenge_bp.post("/start")
@login_required
def start_challenge():
    data = request.get_json(force=True)
    scenario_id = data.get("scenario_id")

    scenario = Scenario.query.get(scenario_id)
    if not scenario:
        return jsonify({"error": "Scenario not found"}), 404

    docker_service = current_app.extensions["docker_service"]

    challenge = docker_service.start_challenge(scenario_id, current_user.id)

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

    # คืนค่าโจทย์กลับไปให้ Frontend แสดงผล
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

    scorer = ScoringService()
    scorer.update_score(
        user_id=current_user.id,
        challenge_id=challenge.id,
        base_delta=15,
        deception_penalty_delta=max(0, (decision["penalty_multiplier"] - 1.0) * 10),
        mtd_evasions_delta=1,
    )

    return jsonify(decision), 200

@challenge_bp.post("/submit")
@login_required
def submit_flag():
    from models import Event, Score, db
    from flask import current_app
    from datetime import datetime

    data = request.get_json(force=True)
    challenge_id = data.get("challenge_id")
    submitted_flag = data.get("flag", "").strip()

    challenge = Challenge.query.get(challenge_id)
    if not challenge:
        return jsonify({"error": "Challenge not found"}), 404

    scenario = Scenario.query.get(challenge.scenario_id)
    if not scenario:
        return jsonify({"error": "Scenario not found"}), 404

    if scenario.flag == submitted_flag:
        if challenge.status == "solved":
            return jsonify({"success": True, "message": "You already solved this challenge!"}), 200

        points = 100
        if scenario.difficulty == 'medium': points = 200
        if scenario.difficulty == 'hard': points = 300

        # 2. ค้นหาหรือสร้าง Score ใหม่
        score_entry = Score.query.filter_by(user_id=current_user.id, challenge_id=challenge.id).first()
        if not score_entry:
            score_entry = Score(
                user_id=current_user.id, 
                challenge_id=challenge.id,
                base_score=0.0,
                net_score=0.0,
                solved=0
            )
            db.session.add(score_entry)
        
        score_entry.base_score = (score_entry.base_score or 0.0) + points
        score_entry.net_score = (score_entry.net_score or 0.0) + points
        score_entry.solved = 1  # อัปเดตว่าโจทย์ข้อนี้ผ่านแล้ว
        score_entry.last_activity = datetime.utcnow()

        # 3. บันทึก Event
        solve_event = Event(
            challenge_id=challenge.id,
            type="score_update",
            details={"message": "Flag captured successfully!", "points_added": points}
        )
        db.session.add(solve_event)
        db.session.commit()

        docker_service = current_app.extensions.get("docker_service")
        if docker_service:
            try:
                docker_service._emit("score_update", {"challenge_id": challenge.id, "points": points})
                docker_service.stop_challenge(challenge.id)
            except Exception as e:
                print(f"Cleanup error: {e}")

        challenge.status = "solved"
        db.session.commit()

        return jsonify({"success": True, "message": f"Correct Flag! +{points} Points!"}), 200
    else:
        return jsonify({"success": False, "message": "Incorrect Flag. Keep trying!"}), 200