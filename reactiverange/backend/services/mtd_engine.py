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

    def decide_action(self, event_type: str) -> dict:
        if event_type == "manual_trigger":
            return {
                "action": "network_ip_hopping",
                "description": "Swapped Victim and Honeypot IPs at the network layer",
            }

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

        if self.state in {"ELEVATED", "CRITICAL"}:
            return {
                "action": "network_ip_hopping",
                "description": "Swapped Victim and Honeypot IPs at the network layer",
            }

        return {
            "action": "observe",
            "description": "Monitoring traffic; no network reroute required",
        }
