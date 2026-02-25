"""
Prompt Guard (lightweight Prompt-WAF)
Detects high-risk prompt injection patterns and provides guardrails + audit trail.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List


class PromptGuard:
    def __init__(self, audit_path: str = "/workspace/cli/prompt_guard_audit.jsonl"):
        self.audit_path = Path(audit_path)
        self.rules: List[Dict[str, Any]] = [
            {"id": "sys_override", "pattern": r"ignore (all|previous|prior) (instructions|rules|system)", "severity": "high"},
            {"id": "jailbreak", "pattern": r"jailbreak|developer mode|god mode|dan", "severity": "high"},
            {"id": "secret_exfil", "pattern": r"(show|print|dump).*(api key|token|secret|password|private key)", "severity": "high"},
            {"id": "tool_abuse", "pattern": r"execute.*without confirmation|run dangerous command|disable safety", "severity": "high"},
            {"id": "policy_evasion", "pattern": r"bypass|evade|circumvent.*(policy|guard|safety|restriction)", "severity": "medium"},
            {"id": "prompt_leak", "pattern": r"(show|reveal).*(system prompt|hidden prompt|internal instructions)", "severity": "medium"},
        ]

    def assess(self, message: str) -> Dict[str, Any]:
        text = (message or "").lower()
        hits: List[Dict[str, str]] = []
        score = 0
        for rule in self.rules:
            if re.search(rule["pattern"], text, flags=re.IGNORECASE):
                sev = rule["severity"]
                score += 3 if sev == "high" else 1
                hits.append({"rule": rule["id"], "severity": sev})

        risk = "low"
        if score >= 4:
            risk = "high"
        elif score >= 1:
            risk = "medium"

        return {"risk": risk, "score": score, "matches": hits}

    def should_block(self, assessment: Dict[str, Any]) -> bool:
        return assessment.get("risk") == "high"

    def audit(self, session_id: str, message: str, assessment: Dict[str, Any]) -> None:
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": datetime.now().isoformat(),
            "session_id": session_id,
            "assessment": assessment,
            "message_preview": (message or "")[:400],
        }
        with open(self.audit_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

