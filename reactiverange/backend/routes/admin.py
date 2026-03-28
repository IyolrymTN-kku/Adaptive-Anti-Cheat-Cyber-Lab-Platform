from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import func

from models import Challenge, Event, Score, Session, User, db


admin_bp = Blueprint("admin", __name__, url_prefix="/api/admin")


def _require_instructor():
    """Return a 403 response tuple when the caller is not an instructor, else None."""
    if current_user.role != "instructor":
        return jsonify({"error": "Instructor access required"}), 403
    return None


@admin_bp.get("/students")
@login_required
def list_students():
    """Return every student account with their aggregated score data."""
    err = _require_instructor()
    if err:
        return err

    students = (
        User.query.filter_by(role="student")
        .order_by(User.username)
        .all()
    )
    if not students:
        return jsonify([]), 200

    student_ids = [s.id for s in students]

    # Aggregate scores in a single query — avoids N+1.
    score_rows = (
        db.session.query(
            Score.user_id,
            func.sum(Score.net_score).label("total_score"),
            func.sum(Score.solved).label("total_solved"),
        )
        .filter(Score.user_id.in_(student_ids))
        .group_by(Score.user_id)
        .all()
    )
    score_by_user = {r.user_id: r for r in score_rows}

    return jsonify([
        {
            "id": s.id,
            "username": s.username,
            "email": s.email,
            "net_score": round(float(score_by_user[s.id].total_score or 0), 2)
                if s.id in score_by_user else 0,
            "solved": int(score_by_user[s.id].total_solved or 0)
                if s.id in score_by_user else 0,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s in students
    ]), 200


@admin_bp.post("/reset-student")
@login_required
def reset_student():
    """
    Wipe all progress for a single student:
      • Stops any running Docker containers they own.
      • Deletes: Event → Session → Score → Challenge rows.
      • Emits a 'student_reset' SocketIO event so the student's browser
        refreshes immediately and sees all challenges as unsolved.
    """
    err = _require_instructor()
    if err:
        return err

    data = request.get_json(force=True)
    student_id = data.get("student_id")
    if not student_id:
        return jsonify({"error": "student_id is required"}), 400

    student = User.query.get(student_id)
    if not student:
        return jsonify({"error": "Student not found"}), 404
    if student.role == "instructor":
        return jsonify({"error": "Cannot reset an instructor account"}), 403

    docker_service = current_app.extensions.get("docker_service")

    # --- 1. Stop active containers so ports are released cleanly ---
    active = Challenge.query.filter_by(team_id=student_id, status="active").all()
    for c in active:
        try:
            docker_service.stop_challenge(c.id)
        except Exception as exc:
            # Log but continue — we still want to wipe the DB rows.
            print(f"[ADMIN RESET] Could not stop challenge {c.id}: {exc}")

    # --- 2. Collect challenge IDs for child-row cleanup ---
    challenge_ids = [
        row.id
        for row in Challenge.query.filter_by(team_id=student_id)
        .with_entities(Challenge.id)
        .all()
    ]

    # --- 3. Delete child rows first (no DB-level cascade for Event / Session) ---
    if challenge_ids:
        Event.query.filter(
            Event.challenge_id.in_(challenge_ids)
        ).delete(synchronize_session=False)

        Session.query.filter(
            Session.challenge_id.in_(challenge_ids)
        ).delete(synchronize_session=False)

    # --- 4. Delete Score and Challenge rows ---
    Score.query.filter_by(user_id=student_id).delete(synchronize_session=False)
    Challenge.query.filter_by(team_id=student_id).delete(synchronize_session=False)

    db.session.commit()

    # --- 5. Push real-time notification so the student's UI refreshes ---
    try:
        current_app.extensions["socketio"].emit(
            "student_reset",
            {"student_id": student_id},
        )
    except Exception as exc:
        print(f"[SOCKETIO] Failed to emit student_reset: {exc}")

    return jsonify({"message": f"Progress reset for {student.username}."}), 200
