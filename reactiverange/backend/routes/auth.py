import random
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user, login_required, login_user, logout_user

from models import User, db


auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")


def _user_to_dict(user: User):
    return {
        "id": user.id,
        "email": user.email,
        "username": user.username,
        "role": user.role,
        "mfa_verified": user.mfa_verified,
    }


@auth_bp.post("/register")
def register():
    data = request.get_json(force=True)
    email = (data.get("email") or "").strip().lower()
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    role = (data.get("role") or "student").strip().lower()

    if role not in {"student", "instructor"}:
        return jsonify({"error": "Invalid role"}), 400

    if not email or not username or len(password) < 8:
        return jsonify({"error": "Email, username, and 8+ char password are required"}), 400

    if User.query.filter((User.email == email) | (User.username == username)).first():
        return jsonify({"error": "User already exists"}), 409

    password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    user = User(email=email, username=username, password_hash=password_hash, role=role)
    db.session.add(user)
    db.session.commit()

    mail_service = current_app.extensions["mail_service"]
    try:
        mail_service.send_welcome_email(email, username)
    except Exception:
        pass

    return jsonify({"message": "Registered successfully", "user": _user_to_dict(user)}), 201


@auth_bp.post("/login")
def login():
    data = request.get_json(force=True)
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({"error": "Invalid credentials"}), 401

    if not bcrypt.checkpw(password.encode("utf-8"), user.password_hash.encode("utf-8")):
        return jsonify({"error": "Invalid credentials"}), 401

    otp = f"{random.randint(0, 999999):06d}"
    user.otp_code = otp
    user.otp_expiry = datetime.utcnow() + timedelta(minutes=current_app.config["OTP_EXPIRY_MINUTES"])
    user.mfa_verified = False
    db.session.commit()

    mail_service = current_app.extensions["mail_service"]
    try:
        mail_service.send_otp_email(user.email, otp)
    except Exception as exc:
        return jsonify({"error": f"Failed to send OTP: {exc}"}), 500

    return jsonify({"requires_otp": True, "user_id": user.id}), 200


@auth_bp.post("/verify-otp")
def verify_otp():
    data = request.get_json(force=True)
    email = (data.get("email") or "").strip().lower()
    otp_code = (data.get("otp") or "").strip()

    user = User.query.filter_by(email=email).first()
    if not user or not user.otp_code:
        return jsonify({"error": "Invalid OTP flow"}), 400

    if user.otp_code != otp_code:
        return jsonify({"error": "Invalid OTP"}), 401

    if not user.otp_expiry or datetime.utcnow() > user.otp_expiry:
        return jsonify({"error": "OTP expired"}), 401

    user.mfa_verified = True
    user.otp_code = None
    user.otp_expiry = None
    db.session.commit()

    login_user(user)
    expiry = datetime.now(timezone.utc) + current_app.config["JWT_EXPIRY"]
    token = jwt.encode(
        {"sub": user.id, "role": user.role, "exp": expiry},
        current_app.config["SECRET_KEY"],
        algorithm="HS256",
    )

    return jsonify({"token": token, "user": _user_to_dict(user)}), 200


@auth_bp.post("/logout")
@login_required
def logout():
    logout_user()
    return jsonify({"message": "Logged out"}), 200


@auth_bp.get("/me")
def me():
    if not current_user.is_authenticated:
        return jsonify({"authenticated": False}), 200
    return jsonify({"authenticated": True, "user": _user_to_dict(current_user)}), 200
