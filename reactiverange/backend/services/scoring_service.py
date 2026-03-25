from datetime import datetime

from models import Event, Score, db


class ScoringService:
    @staticmethod
    def _calc_net(base_score, speed_multiplier, deception_penalty):
        return max((base_score * speed_multiplier) - deception_penalty, 0)

    def update_score(
        self,
        user_id,
        challenge_id,
        base_delta=0,
        speed_multiplier=None,
        deception_penalty_delta=0,
        solved_delta=0,
        deception_hits_delta=0,
        mtd_evasions_delta=0,
    ):
        score = Score.query.filter_by(user_id=user_id, challenge_id=challenge_id).first()
        if not score:
            score = Score(
                user_id=user_id,
                challenge_id=challenge_id,
                base_score=0.0,
                speed_multiplier=1.0,
                deception_penalty=0.0,
                net_score=0.0,
                solved=0,
                deception_hits=0,
                mtd_evasions=0,
            )
            db.session.add(score)

        score.base_score = float(score.base_score or 0.0)
        score.speed_multiplier = float(score.speed_multiplier or 1.0)
        score.deception_penalty = float(score.deception_penalty or 0.0)
        score.solved = int(score.solved or 0)
        score.deception_hits = int(score.deception_hits or 0)
        score.mtd_evasions = int(score.mtd_evasions or 0)

        score.base_score += base_delta
        if speed_multiplier is not None:
            score.speed_multiplier = speed_multiplier
        score.deception_penalty += deception_penalty_delta
        score.solved += solved_delta
        score.deception_hits += deception_hits_delta
        score.mtd_evasions += mtd_evasions_delta
        score.net_score = self._calc_net(score.base_score, score.speed_multiplier, score.deception_penalty)
        score.last_activity = datetime.utcnow()

        db.session.commit()

        event = Event(
            challenge_id=challenge_id,
            type="score_update",
            details={
                "user_id": user_id,
                "net_score": score.net_score,
                "deception_penalty": score.deception_penalty,
            },
        )
        db.session.add(event)
        db.session.commit()
        return score

    @staticmethod
    def get_live_scores():
        return Score.query.order_by(Score.net_score.desc(), Score.last_activity.asc()).all()

    @staticmethod
    def get_user_history(user_id):
        return Score.query.filter_by(user_id=user_id).order_by(Score.updated_at.desc()).all()
