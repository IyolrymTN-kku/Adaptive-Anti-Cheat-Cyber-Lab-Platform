from datetime import datetime

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import JSON


db = SQLAlchemy()


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="student")
    otp_code = db.Column(db.String(6), nullable=True)
    otp_expiry = db.Column(db.DateTime, nullable=True)
    mfa_verified = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class Scenario(db.Model):
    __tablename__ = "scenarios"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    difficulty = db.Column(db.String(20), nullable=False)
    vuln_type = db.Column(db.String(50), nullable=False)
    dockerfile_content = db.Column(db.Text, nullable=False)
    rule_json = db.Column(JSON, nullable=False)
    challenge_description = db.Column(db.Text, nullable=False)
    expected_solution_path = db.Column(db.Text, nullable=False)
    flag = db.Column(db.String(255), nullable=False)
    expected_time = db.Column(db.Integer, nullable=False, default=300)  # seconds, T_expected in scoring formula
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class Challenge(db.Model):
    __tablename__ = "challenges"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    scenario_id = db.Column(db.Integer, db.ForeignKey("scenarios.id"), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="stopped")
    container_id = db.Column(db.String(128), nullable=True)
    current_port = db.Column(db.Integer, nullable=True)  # reused as host-side VNC access port
    team_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    started_at = db.Column(db.DateTime, nullable=True)


class Session(db.Model):
    __tablename__ = "sessions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    challenge_id = db.Column(db.Integer, db.ForeignKey("challenges.id"), nullable=False)
    started_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    ended_at = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(20), default="active", nullable=False)


class Score(db.Model):
    __tablename__ = "scores"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    challenge_id = db.Column(db.Integer, db.ForeignKey("challenges.id"), nullable=False)
    base_score = db.Column(db.Float, default=0.0, nullable=False)
    speed_multiplier = db.Column(db.Float, default=1.0, nullable=False)
    deception_penalty = db.Column(db.Float, default=0.0, nullable=False)
    net_score = db.Column(db.Float, default=0.0, nullable=False)
    solved = db.Column(db.Integer, default=0, nullable=False)
    deception_hits = db.Column(db.Integer, default=0, nullable=False)
    mtd_evasions = db.Column(db.Integer, default=0, nullable=False)
    last_activity = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class Event(db.Model):
    __tablename__ = "events"

    id = db.Column(db.Integer, primary_key=True)
    challenge_id = db.Column(db.Integer, db.ForeignKey("challenges.id"), nullable=False, index=True)
    type = db.Column(db.String(50), nullable=False)
    details = db.Column(JSON, nullable=False, default={})
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
