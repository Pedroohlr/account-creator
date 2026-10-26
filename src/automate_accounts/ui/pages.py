"""Abas do painel: Painel, Nova execução, Contas, Saúde e Configurações."""
from __future__ import annotations

import csv
from datetime import datetime

from pydantic import ValidationError
from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, DataTable, Input, Label, Select, Static, Switch

from ..config import ROOT, AccountsConfig, AppiumConfig, EmulatorConfig, Settings, save_local_settings
from ..core import health
from .estimate import devices_needed, estimate_seconds, fmt_duration
from .theme import AMBER, GREEN, RED
from .widgets import StatCard, level_text, status_text


def _row(label: str, widget, hint: str | None = None) -> Horizontal:
    children = [Label(label), widget]
    if hint:
        children.append(Label(hint, classes="muted"))
    return Horizontal(*children, classes="form-row")


def _int(value: str, lo: int, hi: int, name: str) -> int:
    if not value.strip().lstrip("-").isdigit() or not lo <= int(value) <= hi:
        raise ValueError(f"{name}: informe um número entre {lo} e {hi}.")
    return int(value)


# --------------------------------------------------------------------------
class DashboardPane(Vertical):
    def compose(self) -> ComposeResult:
        yield Label("VISÃO GERAL", classes="section")
        with Horizontal(classes="cards"):
            yield StatCard("Contas criadas", "0", id="d-created", classes="good")
            yield StatCard("Falhas", "0", id="d-failed")
            yield StatCard("Taxa de sucesso", "—", id="d-rate")
            yield StatCard("Tempo médio / conta", "—", id="d-avg")
            yield StatCard("Saúde do ambiente", "não verificada", id="d-health")
        yield Label("CONTAS RECENTES", classes="section")
        yield DataTable(id="d-recent", zebra_stripes=True)
        with Horizontal(classes="buttons"):
            yield Button("▶  Nova execução", id="go-new", variant="primary")
            yield Button("♥  Verificar saúde", id="go-health")

    def on_mount(self) -> None:
        self.query_one("#d-recent", DataTable).add_columns("#", "E-mail", "Dispositivo", "Status", "Tempo", "Data")
        self.refresh_data()

    def refresh_data(self) -> None:
        repo = self.app.repo  # type: ignore[attr-defined]
        counts = repo.counts()
        total = counts["criada"] + counts["falhou"]
        self.query_one("#d-created", StatCard).set(str(counts["criada"]))
        self.query_one("#d-failed", StatCard).set(str(counts["falhou"]), "bad" if counts["falhou"] else "")
        rate = f"{counts['criada'] * 100 / total:.0f}%" if total else "—"
        self.query_one("#d-rate", StatCard).set(rate)
        self.query_one("#d-avg", StatCard).set(fmt_duration(repo.avg_duration()))
        table = self.query_one("#d-recent", DataTable)
        table.clear()
        for r in repo.list_recent(10):
            table.add_row(
                str(r.id), r.email, f"#{r.device}" if r.device else "—", status_text(r.status),
                fmt_duration(r.duration), r.created_at.replace("T", " "),
            )

    def set_health(self, results: dict[str, health.Check]) -> None:
        card = self.query_one("#d-health", StatCard)
        fails = sum(1 for c in results.values() if c.level == health.FAIL)
        warns = sum(1 for c in results.values() if c.level == health.WARN)
        if fails:
            card.set(f"{fails} erro(s)", "bad")
        elif warns:
            card.set(f"{warns} atenção", "")
        else:
            card.set("tudo OK", "good")

    @on(Button.Pressed, "#go-new")
    def go_new(self) -> None:
        self.app.show_tab("tab-new")  # type: ignore[attr-defined]

    @on(Button.Pressed, "#go-health")
    def go_health(self) -> None:
        self.app.show_tab("tab-health")  # type: ignore[attr-defined]


# --------------------------------------------------------------------------
class NewRunPane(VerticalScroll):
    def compose(self) -> ComposeResult:
        yield Label("NOVA EXECUÇÃO", classes="section")
        yield _row("Quantidade de contas", Input(type="integer", id="nr-count"), "1 a 500")
        yield _row("Contas por dispositivo", Input(type="integer", id="nr-per"), "depois disso o dispositivo é trocado")
        yield _row("Tentativas extras por conta", Input(type="integer", id="nr-retries"), "0 a 5")
        yield _row("Limpar dados ao trocar (wipe)", Switch(id="sw-wipe"), "zera o emulador: parece outro aparelho")
        yield _row("User-Agent aleatório por dispositivo", Switch(id="sw-ua"))
        yield _row("Emulador sem janela (headless)", Switch(id="sw-headless"))
        yield Static("", id="estimate")
        with Horizontal(classes="buttons"):
            yield Button("▶  Iniciar", id="start", variant="primary")
            yield Button("Testar infraestrutura", id="smoke")

    def on_mount(self) -> None:
        self.load_defaults()

    def load_defaults(self) -> None:
        s: Settings = self.app.settings  # type: ignore[attr-defined]
        self.query_one("#nr-count", Input).value = str(s.accounts.count)
        self.query_one("#nr-per", Input).value = str(s.accounts.per_device)
        self.query_one("#nr-retries", Input).value = str(s.accounts.retries)
        self.query_one("#sw-wipe", Switch).value = s.accounts.wipe_on_rotate
        self.query_one("#sw-ua", Switch).value = s.accounts.random_user_agent
        self.query_one("#sw-headless", Switch).value = s.emulator.headless
        self.update_estimate()

    def values(self) -> tuple[int, int, int]:
        return (
            _int(self.query_one("#nr-count", Input).value, 1, 500, "Quantidade"),
            _int(self.query_one("#nr-per", Input).value, 1, 500, "Contas por dispositivo"),
            _int(self.query_one("#nr-retries", Input).value, 0, 5, "Tentativas extras"),
        )

    @on(Input.Changed)
    @on(Switch.Changed)
    def update_estimate(self) -> None:
        box = self.query_one("#estimate", Static)
        try:
            count, per, _ = self.values()
        except ValueError as exc:
            box.update(f"[{AMBER}]{exc}[/]")
            return
        wipe = self.query_one("#sw-wipe", Switch).value
        avg = self.app.repo.avg_duration()  # type: ignore[attr-defined]
        total = estimate_seconds(count, per, wipe, avg)
        devices = devices_needed(count, per)
        base = "média real das suas últimas contas" if avg else "tempo padrão medido"
        box.update(
            f"[bold {GREEN}]Estimativa: ≈ {fmt_duration(total)}[/]   ·   {devices} dispositivo(s)   ·   "
            f"{fmt_duration(avg or 140)} por conta ({base})"
        )

    def apply(self) -> int | None:
        """Aplica os valores da tela às configurações em memória; devolve a quantidade."""
        try:
            count, per, retries = self.values()
        except ValueError as exc:
            self.notify(str(exc), severity="error")
            return None
        s: Settings = self.app.settings  # type: ignore[attr-defined]
        s.accounts.count, s.accounts.per_device, s.accounts.retries = count, per, retries
        s.accounts.wipe_on_rotate = self.query_one("#sw-wipe", Switch).value
        s.accounts.random_user_agent = self.query_one("#sw-ua", Switch).value
        s.emulator.headless = self.query_one("#sw-headless", Switch).value
        return count

    @on(Button.Pressed, "#start")
    def start(self) -> None:
        if (count := self.apply()) is not None:
            self.app.start_batch(count)  # type: ignore[attr-defined]

    @on(Button.Pressed, "#smoke")
    def smoke(self) -> None:
        self.apply()
        self.app.start_smoke()  # type: ignore[attr-defined]


# --------------------------------------------------------------------------
class AccountsPane(Vertical):
    STATUS_OPTIONS = [("Todas", ""), ("Criadas", "criada"), ("Falhas", "falhou")]

    def compose(self) -> ComposeResult:
        yield Label("CONTAS", classes="section")
        with Horizontal(classes="buttons"):
            yield Input(placeholder="buscar por e-mail...", id="a-search")
            yield Select(self.STATUS_OPTIONS, value="", allow_blank=False, id="a-status")
            yield Button("Atualizar", id="a-refresh")
            yield Button("Exportar CSV", id="a-export", variant="primary")
        yield Static("", id="a-count", classes="hint")
        yield DataTable(id="a-table", zebra_stripes=True)

    def on_mount(self) -> None:
        table = self.query_one("#a-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("#", "E-mail", "Senha", "Dispositivo", "Status", "Tempo", "Data", "Erro")
        self.refresh_data()

    def current(self):
        text = self.query_one("#a-search", Input).value.strip()
        status = self.query_one("#a-status", Select).value or None
        return self.app.repo.search(text, status)  # type: ignore[attr-defined]

    def refresh_data(self) -> None:
        rows = self.current()
        table = self.query_one("#a-table", DataTable)
        table.clear()
        for r in rows:
            table.add_row(
                str(r.id), r.email, r.password, f"#{r.device}" if r.device else "—",
                status_text(r.status), fmt_duration(r.duration),
                r.created_at.replace("T", " "), (r.error or "")[:60],
            )
        self.query_one("#a-count", Static).update(f"{len(rows)} conta(s) (máx. 500)")

    @on(Input.Changed, "#a-search")
    @on(Select.Changed, "#a-status")
    @on(Button.Pressed, "#a-refresh")
    def filters_changed(self) -> None:
        self.refresh_data()

    @on(Button.Pressed, "#a-export")
    def export(self) -> None:
        rows = self.current()
        out_dir = ROOT / "exports"
        out_dir.mkdir(exist_ok=True)
        path = out_dir / f"contas_{datetime.now():%Y%m%d_%H%M%S}.csv"
        with path.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerow(["id", "email", "senha", "status", "dispositivo", "duracao_s", "data", "erro"])
            for r in rows:
                writer.writerow([r.id, r.email, r.password, r.status, r.device or "",
                                 round(r.duration, 1) if r.duration else "", r.created_at, r.error or ""])
        self.notify(f"{len(rows)} conta(s) exportadas para {path.relative_to(ROOT)}")


# --------------------------------------------------------------------------
class HealthPane(Vertical):
    def compose(self) -> ComposeResult:
        yield Label("SAÚDE DA APLICAÇÃO", classes="section")
        yield Static("Verificando...", id="h-summary", classes="hint")
        yield DataTable(id="h-table", zebra_stripes=True)
        with Horizontal(classes="buttons"):
            yield Button("♥  Verificar agora", id="h-run", variant="primary")

    def on_mount(self) -> None:
        table = self.query_one("#h-table", DataTable)
        table.cursor_type = "row"
        table.add_column("Status", key="status", width=11)
        table.add_column("Verificação", key="name", width=26)
        table.add_column("Detalhe", key="detail", width=44)
        table.add_column("Como resolver", key="hint")
        self.ran_once = False

    def run_all(self) -> None:
        self.ran_once = True
        table = self.query_one("#h-table", DataTable)
        table.clear()
        for name, _ in self.app.health_checks:  # type: ignore[attr-defined]
            table.add_row(Text("…", style="dim"), name, "verificando...", "", key=name)
        self.query_one("#h-summary", Static).update("Verificando...")
        self._work()

    @work(thread=True, exclusive=True)
    def _work(self) -> None:
        app = self.app
        results: dict[str, health.Check] = {}
        for name, fn in app.health_checks:  # type: ignore[attr-defined]
            check = health.run_check(name, fn, app.settings)  # type: ignore[attr-defined]
            results[name] = check
            app.call_from_thread(self._show, name, check)
        app.call_from_thread(self._done, results)

    def _show(self, name: str, check: health.Check) -> None:
        table = self.query_one("#h-table", DataTable)
        table.update_cell(name, "status", level_text(check.level))
        table.update_cell(name, "detail", check.detail, update_width=True)
        table.update_cell(name, "hint", check.hint, update_width=True)

    def _done(self, results: dict[str, health.Check]) -> None:
        fails = sum(1 for c in results.values() if c.level == health.FAIL)
        warns = sum(1 for c in results.values() if c.level == health.WARN)
        oks = len(results) - fails - warns
        color = RED if fails else AMBER if warns else GREEN
        self.query_one("#h-summary", Static).update(
            f"[{color}]{oks} de {len(results)} OK · {warns} atenção · {fails} erro(s)[/]"
        )
        self.app.on_health(results)  # type: ignore[attr-defined]

    @on(Button.Pressed, "#h-run")
    def rerun(self) -> None:
        self.run_all()


# --------------------------------------------------------------------------
class SettingsPane(VerticalScroll):
    BINDINGS = [Binding("ctrl+s", "save_settings", "Salvar")]

    def compose(self) -> ComposeResult:
        s: Settings = self.app.settings  # type: ignore[attr-defined]
        yield Label("CONFIGURAÇÕES", classes="section")
        yield _row("URL do site", Input(s.target_url, id="st-url"))
        yield _row("AVD (emulador)", Select([(s.avd_name, s.avd_name)], value=s.avd_name, allow_blank=False, id="st-avd"))
        yield Label("Emulador", classes="section")
        yield _row("Sem janela (headless)", Switch(s.emulator.headless, id="st-headless"))
        yield _row("Zerar dados no 1º boot", Switch(s.emulator.wipe_data, id="st-wipe-first"))
        yield _row("Timeout de boot (s)", Input(str(s.emulator.boot_timeout), type="integer", id="st-boot"))
        yield _row("Folga após o boot (s)", Input(str(s.emulator.settle_seconds), type="integer", id="st-settle"))
        yield Label("Appium", classes="section")
        yield _row("Porta", Input(str(s.appium.port), type="integer", id="st-port"))
        yield Label("Contas", classes="section")
        yield _row("Quantidade padrão", Input(str(s.accounts.count), type="integer", id="st-count"))
        yield _row("Contas por dispositivo", Input(str(s.accounts.per_device), type="integer", id="st-per"))
        yield _row("Tentativas extras por conta", Input(str(s.accounts.retries), type="integer", id="st-retries"))
        yield _row("Pausa entre contas (s)", Input(str(s.accounts.delay_between), id="st-delay"))
        yield _row("Limpar dados ao trocar (wipe)", Switch(s.accounts.wipe_on_rotate, id="st-wipe"))
        yield _row("User-Agent aleatório por dispositivo", Switch(s.accounts.random_user_agent, id="st-ua"))
        with Horizontal(classes="buttons"):
            yield Button("Salvar", id="st-save", variant="primary")
            yield Button("Restaurar padrão", id="st-reset", variant="error")

    def on_mount(self) -> None:
        self.load_avds()

    @work(thread=True)
    def load_avds(self) -> None:
        try:
            avds = self.app.emulator_avds()  # type: ignore[attr-defined]
        except Exception:
            return
        if avds:
            self.app.call_from_thread(self._set_avds, avds)

    def _set_avds(self, avds: list[str]) -> None:
        select = self.query_one("#st-avd", Select)
        current = select.value
        names = list(avds) if current in avds else [current, *avds]
        select.set_options([(n, n) for n in names])
        select.value = current

    def build(self) -> Settings:
        q = self.query_one
        s: Settings = self.app.settings  # type: ignore[attr-defined]
        return Settings(
            target_url=q("#st-url", Input).value.strip(),
            avd_name=str(q("#st-avd", Select).value),
            android_home=s.android_home,
            emulator=EmulatorConfig(
                headless=q("#st-headless", Switch).value,
                wipe_data=q("#st-wipe-first", Switch).value,
                boot_timeout=_int(q("#st-boot", Input).value, 30, 1800, "Timeout de boot"),
                settle_seconds=_int(q("#st-settle", Input).value, 0, 300, "Folga após o boot"),
            ),
            appium=AppiumConfig(port=_int(q("#st-port", Input).value, 1, 65535, "Porta"),
                                host=s.appium.host, startup_timeout=s.appium.startup_timeout),
            accounts=AccountsConfig(
                count=_int(q("#st-count", Input).value, 1, 500, "Quantidade"),
                per_device=_int(q("#st-per", Input).value, 1, 500, "Contas por dispositivo"),
                retries=_int(q("#st-retries", Input).value, 0, 5, "Tentativas extras"),
                delay_between=float(q("#st-delay", Input).value.replace(",", ".") or 0),
                wipe_on_rotate=q("#st-wipe", Switch).value,
                random_user_agent=q("#st-ua", Switch).value,
            ),
        )

    def action_save_settings(self) -> None:
        self.save()

    @on(Button.Pressed, "#st-save")
    def save(self) -> None:
        try:
            new = self.build()
            if not new.target_url.startswith(("http://", "https://")):
                raise ValueError("URL do site deve começar com http:// ou https://")
        except (ValueError, ValidationError) as exc:
            self.notify(str(exc).splitlines()[0], severity="error")
            return
        self.app.apply_settings(new)  # type: ignore[attr-defined]
        self.notify("Configurações salvas.")

    @on(Button.Pressed, "#st-reset")
    def reset(self) -> None:
        self.app.reset_settings()  # type: ignore[attr-defined]
        self.notify("Configurações restauradas para o padrão.")
