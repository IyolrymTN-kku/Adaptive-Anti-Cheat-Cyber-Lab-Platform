import json
import time

from flask import Blueprint, Response, request, stream_with_context
from flask_login import current_user, login_required

from models import Challenge, Event


events_bp = Blueprint("events", __name__, url_prefix="/api/events")


@events_bp.get("/stream")
@login_required
def stream_events():
    challenge_id = request.args.get("challenge_id", type=int)
    if not challenge_id:
        return Response("challenge_id is required", status=400)

    challenge = Challenge.query.get(challenge_id)
    if not challenge:
        return Response("Challenge not found", status=404)

    if current_user.role != "instructor" and challenge.team_id != current_user.id:
        return Response("Forbidden", status=403)

    def event_stream():
        last_seen = 0
        while True:
            rows = (
                Event.query.filter(Event.challenge_id == challenge_id, Event.id > last_seen)
                .order_by(Event.id.asc())
                .limit(50)
                .all()
            )
            for row in rows:
                last_seen = row.id
                payload = {
                    "id": row.id,
                    "type": row.type,
                    "details": row.details,
                    "timestamp": row.timestamp.isoformat(),
                }
                yield f"data: {json.dumps(payload)}\n\n"
            time.sleep(1)

    return Response(stream_with_context(event_stream()), mimetype="text/event-stream")
