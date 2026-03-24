from flask import Blueprint, jsonify
from flask_login import login_required

from models import User
from services.scoring_service import ScoringService


scoreboard_bp = Blueprint("scoreboard", __name__, url_prefix="/api/scores")


@scoreboard_bp.get("/live")
@login_required
def live_scores():
    scores = ScoringService.get_live_scores()

    payload = []
    for rank, score in enumerate(scores, start=1):
        user = User.query.get(score.user_id)
        payload.append(
            {
                "rank": rank,
                "user_id": score.user_id,
                "team": user.username if user else f"User {score.user_id}",
                "net_score": round(score.net_score, 2),
                "solved": score.solved,
                "deception_hits": score.deception_hits,
                "mtd_evasions": score.mtd_evasions,
                "last_activity": score.last_activity.isoformat() if score.last_activity else None,
            }
        )

    return jsonify(payload), 200


@scoreboard_bp.get("/history")
@login_required
def history():
    from flask_login import current_user

    rows = ScoringService.get_user_history(current_user.id)
    return (
        jsonify(
            [
                {
                    "challenge_id": s.challenge_id,
                    "base_score": s.base_score,
                    "speed_multiplier": s.speed_multiplier,
                    "deception_penalty": s.deception_penalty,
                    "net_score": s.net_score,
                    "updated_at": s.updated_at.isoformat(),
                }
                for s in rows
            ]
        ),
        200,
    )
