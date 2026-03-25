from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user, login_required

from models import Scenario, db


scenario_bp = Blueprint("scenario", __name__, url_prefix="/api/scenario")


@scenario_bp.post("/generate")
@login_required
def generate_scenario():
    if current_user.role != "instructor":
        return jsonify({"error": "Only instructors can generate scenarios"}), 403

    data = request.get_json(force=True)
    vuln_type = data.get("vuln_type")
    difficulty = data.get("difficulty")
    custom_description = data.get("custom_description", "")

    if vuln_type not in {"sql_injection", "xss", "cmd_injection"}:
        return jsonify({"error": "Invalid vuln_type"}), 400

    if difficulty not in {"easy", "medium", "hard"}:
        return jsonify({"error": "Invalid difficulty"}), 400

    gemini_service = current_app.extensions["gemini_service"]
    try:
        payload = gemini_service.generate_scenario(vuln_type, difficulty, custom_description)
    except Exception as exc:
        return jsonify({"error": f"Scenario generation failed: {exc}"}), 502

    scenario = Scenario(
        name=f"{vuln_type.replace('_', ' ').title()} ({difficulty.title()})",
        difficulty=difficulty,
        vuln_type=vuln_type,
        dockerfile_content=payload["dockerfile_content"],
        rule_json=payload["rule_json"],
        challenge_description=payload["challenge_description"],
        expected_solution_path=payload["expected_solution_path"],
        flag=payload["flag"],
        created_by=current_user.id,
    )
    db.session.add(scenario)
    db.session.commit()

    return (
        jsonify(
            {
                "scenario_id": scenario.id,
                "preview": {
                    "name": scenario.name,
                    "difficulty": scenario.difficulty,
                    "vuln_type": scenario.vuln_type,
                    "dockerfile_content": scenario.dockerfile_content,
                    "rule_json": scenario.rule_json,
                    "challenge_description": scenario.challenge_description,
                    "expected_solution_path": scenario.expected_solution_path,
                    "flag": scenario.flag,
                },
            }
        ),
        201,
    )


@scenario_bp.get("/list")
@login_required
def list_scenarios():
    query = Scenario.query
    if current_user.role != "instructor":
        query = query.filter_by(created_by=current_user.id)

    rows = query.order_by(Scenario.created_at.desc()).all()
    return (
        jsonify(
            [
                {
                    "id": s.id,
                    "name": s.name,
                    "difficulty": s.difficulty,
                    "vuln_type": s.vuln_type,
                    "challenge_description": s.challenge_description,
                    "rule_json": s.rule_json,
                    "created_at": s.created_at.isoformat(),
                }
                for s in rows
            ]
        ),
        200,
    )


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
