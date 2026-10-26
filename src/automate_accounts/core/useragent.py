"""User-Agent móvel aleatório (opcional) para variar a identidade a cada dispositivo."""
from __future__ import annotations

import secrets

# (modelo, versão do Android)
PROFILES = [
    ("Pixel 8", "14"), ("Pixel 7", "14"), ("Pixel 7 Pro", "13"), ("Pixel 6a", "13"),
    ("SM-S918B", "14"), ("SM-A546E", "14"), ("SM-G991B", "13"), ("SM-A336E", "13"),
    ("M2102J20SG", "13"), ("CPH2451", "14"), ("2201116SG", "12"),
]
DEFAULT_CHROME_MAJOR = "131"


def random_user_agent(chrome_major: str | None = None) -> str:
    model, android = secrets.choice(PROFILES)
    major = chrome_major or DEFAULT_CHROME_MAJOR
    return (
        f"Mozilla/5.0 (Linux; Android {android}; {model}) AppleWebKit/537.36 "
        f"(KHTML, like Gecko) Chrome/{major}.0.0.0 Mobile Safari/537.36"
    )
