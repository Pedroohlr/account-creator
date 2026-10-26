"""Geração de dados fictícios para as contas de teste."""
from __future__ import annotations

import re
import secrets
import string
import unicodedata
from dataclasses import dataclass

from faker import Faker

_fake = Faker("pt_BR")
_SYMBOLS = "!@#$%&*?"
GENDERS = ("female", "male", "unspecified")


@dataclass(frozen=True)
class AccountData:
    first_name: str
    last_name: str
    day: int
    month: int          # 1-12
    year: int
    gender: str         # value do select: female | male | unspecified
    username: str       # só a parte antes de @auth4.app
    password: str

    @property
    def email(self) -> str:
        return f"{self.username}@auth4.app"


def _ascii(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def make_username(first: str, last: str) -> str:
    """Aceita letras, números e pontos; o sufixo numérico evita colisões."""
    base = re.sub(r"[^a-z0-9]", "", _ascii(first).lower())
    surname = re.sub(r"[^a-z0-9]", "", _ascii(last).lower())
    return f"{base}.{surname}{secrets.randbelow(900_000) + 100_000}"


def make_password(length: int = 14) -> str:
    """Garante letra maiúscula, minúscula, número e símbolo."""
    pools = [string.ascii_uppercase, string.ascii_lowercase, string.digits, _SYMBOLS]
    chars = [secrets.choice(p) for p in pools]
    alphabet = "".join(pools)
    chars += [secrets.choice(alphabet) for _ in range(length - len(chars))]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


def generate_account() -> AccountData:
    first, last = _fake.first_name(), _fake.last_name()
    return AccountData(
        first_name=first,
        last_name=last,
        day=secrets.randbelow(28) + 1,
        month=secrets.randbelow(12) + 1,
        year=secrets.randbelow(2005 - 1960 + 1) + 1960,
        gender=secrets.choice(GENDERS),
        username=make_username(first, last),
        password=make_password(),
    )
