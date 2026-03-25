import os

from dotenv import load_dotenv
from flask import Flask, jsonify
from flask_cors import CORS
from flask_login import LoginManager
from flask_mail import Mail
from flask_socketio import SocketIO
import jwt

from config import Config
from models import User, db
from routes import auth_bp, challenge_bp, events_bp, scenario_bp, scoreboard_bp
from services.docker_service import DockerService
from services.gemini_service import GeminiService
from services.mail_service import MailService


mail = Mail()
login_manager = LoginManager()
socketio = SocketIO(cors_allowed_origins="*", async_mode="threading")


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


@login_manager.request_loader
def load_user_from_request(request):
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None

    token = auth_header.split(" ", 1)[1].strip()
    if not token:
        return None

    try:
        payload = jwt.decode(token, Config.SECRET_KEY, algorithms=["HS256"])
    except Exception:
        return None

    user_id = payload.get("sub")
    if not user_id:
        return None
    return db.session.get(User, int(user_id))


def create_app():
    load_dotenv()

    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    mail.init_app(app)
    login_manager.init_app(app)
    socketio.init_app(app)
    CORS(app, supports_credentials=True)

    with app.app_context():
        db.create_all()

        app.extensions["mail_service"] = MailService(mail)
        app.extensions["gemini_service"] = GeminiService(app.config["GEMINI_API_KEY"])
        app.extensions["docker_service"] = DockerService(socketio=socketio)

    app.register_blueprint(auth_bp)
    app.register_blueprint(challenge_bp)
    app.register_blueprint(scenario_bp)
    app.register_blueprint(scoreboard_bp)
    app.register_blueprint(events_bp)

    @app.get("/api/health")
    def health():
        return jsonify({"status": "ok", "service": "ReactiveRange backend"})

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    print(f"🚀 ReactiveRange Backend is running on http://127.0.0.1:{port}")
    socketio.run(app, host="0.0.0.0", port=port)
