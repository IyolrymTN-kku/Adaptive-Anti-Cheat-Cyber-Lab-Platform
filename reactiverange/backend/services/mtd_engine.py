import random


class AdaptiveMTDEngine:
    def __init__(self):
        self.attack_count = 0
        self.honeypot_hits = 0
        self.consecutive_attacks = 0
        self.state = "NORMAL"

    def _update_state(self):
        if self.attack_count > 7 or self.consecutive_attacks >= 3:
            self.state = "CRITICAL"
        elif 3 <= self.attack_count <= 7:
            self.state = "ELEVATED"
        else:
            self.state = "NORMAL"

    def _weighted_action(self):
        # This is a simplified policy pi(a|s): action probabilities are conditioned
        # on state s, analogous to an MDP where defender actions aim to maximize
        # attacker disruption cost under observed attack persistence.
        policy = {
            "NORMAL": {
                "port_migrate": 0.70,
                "add_honeypot": 0.20,
                "increase_penalty": 0.10,
            },
            "ELEVATED": {
                "port_migrate": 0.50,
                "add_honeypot": 0.40,
                "score_cap_tighten": 0.10,
            },
            "CRITICAL": {
                "port_migrate": 0.30,
                "session_throttle": 0.40,
                "honeypot_swarm": 0.30,
            },
        }
        actions = list(policy[self.state].keys())
        weights = list(policy[self.state].values())
        return random.choices(actions, weights=weights, k=1)[0]

    def decide_action(self, event_type: str) -> dict:
        if event_type == "attack_detected":
            self.attack_count += 1
            self.consecutive_attacks += 1
        elif event_type == "honeypot_hit":
            self.honeypot_hits += 1
            self.attack_count += 1
            self.consecutive_attacks += 1
        else:
            self.consecutive_attacks = 0

        self._update_state()
        action = self._weighted_action()

        penalty_multiplier = 1.0
        new_port = None

        if action == "port_migrate":
            new_port = random.randint(1024, 65535)
            penalty_multiplier = 1.1 if self.state == "NORMAL" else 1.2
        elif action == "add_honeypot":
            penalty_multiplier = 1.25
        elif action == "increase_penalty":
            penalty_multiplier = 1.35
        elif action == "score_cap_tighten":
            penalty_multiplier = 1.5
        elif action == "session_throttle":
            penalty_multiplier = 1.6
        elif action == "honeypot_swarm":
            penalty_multiplier = 1.8

        return {
            "state": self.state,
            "action": action,
            "new_port": new_port,
            "penalty_multiplier": penalty_multiplier,
            "log_message": f"MTD policy selected '{action}' in state {self.state}.",
        }
