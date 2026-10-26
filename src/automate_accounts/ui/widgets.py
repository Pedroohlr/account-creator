"""Widgets reutilizáveis do painel."""
from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Label

from .theme import AMBER, GREEN, RED


class StatCard(Vertical):
    """Cartão com título e um valor grande (ex.: 'Criadas' / '42')."""

    def __init__(self, title: str, value: str = "—", *, classes: str = "", id: str | None = None) -> None:
        super().__init__(classes=classes, id=id)
        self._title = title
        self._value = value

    def compose(self) -> ComposeResult:
        yield Label(self._title, classes="card-title")
        yield Label(self._value, classes="card-value")

    def set(self, value: str, tone: str | None = None) -> None:
        self.query_one(".card-value", Label).update(value)
        if tone is not None:
            self.remove_class("good", "bad")
            if tone:
                self.add_class(tone)


def status_text(status: str) -> Text:
    return Text("✔ criada", style=GREEN) if status == "criada" else Text("✘ falhou", style=RED)


def level_text(level: str) -> Text:
    return {
        "ok": Text("✔ OK", style=GREEN),
        "warn": Text("▲ atenção", style=AMBER),
        "fail": Text("✘ erro", style=RED),
    }.get(level, Text("…", style="dim"))
