"""
Secret detection module — uses regex to identify common sensitive patterns.
"""

from __future__ import annotations

import re
from typing import NamedTuple

class Finding(NamedTuple):
    """A secret found in a string."""
    secret_type: str
    line_number: int

# Common patterns for sensitive information
PATTERNS = {
    "AWS Access Key ID": r"(?i)AKIA[0-9A-Z]{16}",
    "AWS Secret Access Key": r"(?i)SECRET_?[A-Z0-9]{20,40}",
    "GitHub Personal Access Token": r"ghp_[a-zA-Z0-9]{36}",
    "Slack Webhook URL": r"https://hooks\.slack\.com/services/T[a-zA-Z0-9_]+/B[a-zA-Z0-9_]+/[a-zA-Z0-9_]+",
    "Stripe API Key": r"(?i)sk_live_[0-9a-zA-Z]{24}",
    "Google API Key": r"AIza[0-9A-Za-z-_]{35}",
    "Generic API/Secret Key": r"(?i)(api[_-]?key|secret[_-]?key|password|auth[_-]?token)[\s:=]+['\"]([a-zA-Z0-9]{16,})['\"]"
}

# Pre-compile regexes for performance
COMPILED_PATTERNS = {name: re.compile(pattern) for name, pattern in PATTERNS.items()}

def scan_content(content: str) -> list[Finding]:
    """Scan string content for secrets and return a list of findings."""
    findings: list[Finding] = []
    lines = content.splitlines()
    
    for line_num, line in enumerate(lines, start=1):
        for name, regex in COMPILED_PATTERNS.items():
            if regex.search(line):
                findings.append(Finding(secret_type=name, line_number=line_num))
                
    return findings
