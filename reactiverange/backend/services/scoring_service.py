from datetime import datetime

from models import Event, Score, db

# --- Formula constants ---
# W_a,i : difficulty weight (base score ceiling per challenge)
DIFFICULTY_WEIGHTS = {"easy": 100, "medium": 200, "hard": 300}

# T_expected,i : expected solve time in seconds per difficulty
EXPECTED_TIMES = {"easy": 300, "medium": 600, "hard": 900}

# W_p,j : penalty weight deducted per honeypot/deception hit
PENALTY_WEIGHT = 20

# Score cap: max(S) = SCORE_CAP_MULTIPLIER × W_a
SCORE_CAP_MULTIPLIER = 2


class ScoringService:
    @staticmethod
    def _calc_solve_score(difficulty, t_actual, deception_hits, t_expected=None):
        """
        Implements the paper formula for a single challenge solve:

            S_total = max(0, min(W_a × (T_expected / T_actual) − W_p × E_trap,
                                 W_a × SCORE_CAP_MULTIPLIER))

        - W_a          : difficulty weight
        - T_expected   : instructor-defined expected solve time (seconds).
                         Falls back to EXPECTED_TIMES[difficulty] if not provided.
        - T_actual     : actual time taken (seconds, min=1 to avoid div/0)
        - W_p          : penalty weight per deception hit
        - E_trap       : total deception/honeypot hits accumulated
        """
        w_a = float(DIFFICULTY_WEIGHTS.get(difficulty, 100))
        t_exp = float(t_expected) if t_expected is not None else float(EXPECTED_TIMES.get(difficulty, 300))
        t_actual = max(float(t_actual), 1.0)

        speed_component = w_a * (t_exp / t_actual)
        penalty_component = PENALTY_WEIGHT * int(deception_hits)

        raw = speed_component - penalty_component
        cap = w_a * SCORE_CAP_MULTIPLIER
        return max(0.0, min(raw, cap))

    def record_solve(self, user_id, challenge_id, difficulty, t_actual, t_expected=None):
        """
        Called when a student submits the correct flag.
        Calculates net_score via the paper formula and marks solved=1.
        Preserves previously accumulated deception_hits and mtd_evasions.

        t_expected: Scenario.expected_time set by the instructor (seconds).
                    If None, falls back to the default per difficulty level.
        """
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

        w_a = float(DIFFICULTY_WEIGHTS.get(difficulty, 100))
        t_exp = float(t_expected) if t_expected is not None else float(EXPECTED_TIMES.get(difficulty, 300))
        t_actual = max(float(t_actual), 1.0)
        deception_hits = int(score.deception_hits or 0)

        net = self._calc_solve_score(difficulty, t_actual, deception_hits, t_expected=t_exp)

        # Store decomposed components so scoreboard can show details
        score.base_score = w_a
        score.speed_multiplier = round(t_exp / t_actual, 4)
        score.deception_penalty = float(PENALTY_WEIGHT * deception_hits)
        score.net_score = net
        score.solved = 1
        score.last_activity = datetime.utcnow()

        db.session.commit()

        event = Event(
            challenge_id=challenge_id,
            type="score_update",
            details={
                "user_id": user_id,
                "net_score": net,
                "base_score": w_a,
                "speed_multiplier": score.speed_multiplier,
                "deception_penalty": score.deception_penalty,
                "deception_hits": deception_hits,
                "t_actual": t_actual,
                "t_expected": t_exp,
            },
        )
        db.session.add(event)
        db.session.commit()
        return score

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
        """
        Incremental update used by MTD triggers, resets, and honeypot hits.
        Recalculates net_score after each update using:
            net = max(0, base_score * speed_multiplier - deception_penalty)
        """
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

        score.net_score = max(
            0.0,
            (score.base_score * score.speed_multiplier) - score.deception_penalty,
        )
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
