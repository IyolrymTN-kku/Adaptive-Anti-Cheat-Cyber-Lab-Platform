from flask import Blueprint, jsonify
from flask_login import login_required

from models import User, Score, db
from services.scoring_service import ScoringService
from sqlalchemy import func

scoreboard_bp = Blueprint("scoreboard", __name__, url_prefix="/api/scores")


@scoreboard_bp.get("/live")
@login_required
def live_scores():
    results = db.session.query(
        User.id,
        User.username,
        func.sum(Score.net_score).label("total_net_score"),
        func.sum(Score.solved).label("total_solved"),
        func.sum(Score.deception_hits).label("total_deceptions"),
        func.sum(Score.mtd_evasions).label("total_evasions"),
        func.max(Score.last_activity).label("last_active")
    ).join(Score, User.id == Score.user_id)\
     .group_by(User.id, User.username)\
     .order_by(func.sum(Score.net_score).desc())\
     .all()

    payload = []
    for rank, r in enumerate(results, start=1):
        payload.append(
            {
                "rank": rank,
                "user_id": r.id,
                # เปลี่ยน key จาก 'team' เป็น 'team_name' หรือตามที่ Frontend คุณเรียกใช้ 
                # (แต่หน้าจอคุณใช้ Team/User เลยให้เป็น team ตามเดิมก็ได้)
                "team": r.username,
                "net_score": round(r.total_net_score or 0, 2),
                "solved": int(r.total_solved or 0),
                "deception_hits": int(r.total_deceptions or 0),
                "mtd_evasions": int(r.total_evasions or 0),
                "last_activity": r.last_active.isoformat() if r.last_active else None,
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