from routes.admin import admin_bp
from routes.auth import auth_bp
from routes.challenge import challenge_bp
from routes.events import events_bp
from routes.scenario import scenario_bp
from routes.scoreboard import scoreboard_bp

__all__ = [
    "admin_bp",
    "auth_bp",
    "challenge_bp",
    "events_bp",
    "scenario_bp",
    "scoreboard_bp",
]
