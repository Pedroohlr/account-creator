"""Aba Lotes: histórico de lotes com detalhes, log, relatório e retomada."""
from __future__ import annotations

import logging

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable, Label, RichLog, Static, Switch

from ..config import ROOT
from ..data import batches as bs
from ..data import report
from .estimate import fmt_duration
from .theme import AMBER, GREEN, GREEN_SOFT, RED

STATUS_STYLE = {
    bs.DONE: GREEN, bs.RUNNING: AMBER, bs.PAUSED: AMBER, bs.INTERRUPTED: AMBER,
    bs.FAILED: RED, bs.PLANNED: "dim",
}
LEVEL_STYLE = {"ERROR": RED, "CRITICAL": RED, "WARNING": AMBER}


class BatchesPane(Vertical):
    def __init__(self) -> None:
        super().__init__()
        self.selected: int | None = None
        self.confirm_delete: int | None = None

    def compose(self) -> ComposeResult:
        yield Label("LOTES", classes="section")
        yield DataTable(id="b-table", zebra_stripes=True)
        with Horizontal(classes="buttons"):
            yield Button("▶  Iniciar / retomar", id="b-run", variant="primary")
            yield Button("Relatório", id="b-export")
            yield Button("Excluir", id="b-delete", variant="error")
            yield Button("Atualizar", id="b-refresh")
            yield Label("Só avisos e erros", classes="muted")
            yield Switch(id="b-only-warn")
        with Horizontal(id="b-bottom"):
            yield Static("Selecione um lote.", id="b-detail")
            yield RichLog(id="b-log", markup=False, wrap=True)

    def on_mount(self) -> None:
        table = self.query_one("#b-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("#", "Nome", "Status", "Progresso", "Criadas", "Falhas", "Disp.", "Tempo", "Custo", "Criado em")
        self.refresh_data()

    # -- dados ----------------------------------------------------------------
    @property
    def repo(self) -> bs.BatchRepository:
        return self.app.batches  # type: ignore[attr-defined]

    def refresh_data(self) -> None:
        table = self.query_one("#b-table", DataTable)
        table.clear()
        for b in self.repo.list_all():
            table.add_row(
                str(b.id), b.name, Text(b.status, style=STATUS_STYLE.get(b.status, "")),
                f"{b.done}/{b.target_count}", str(b.created), str(b.failed), str(b.devices),
                fmt_duration(b.active_seconds), report.fmt_money(b.cost, b.currency),
                b.created_at.replace("T", " "), key=str(b.id),
            )
        if self.selected is not None:
            try:
                table.move_cursor(row=table.get_row_index(str(self.selected)))
            except Exception:
                self.selected = None
        self.show_detail()

    def show_detail(self) -> None:
        detail, log_widget = self.query_one("#b-detail", Static), self.query_one("#b-log", RichLog)
        log_widget.clear()
        batch = self.repo.get(self.selected) if self.selected is not None else None
        if batch is None:
            detail.update("Selecione um lote.")
            return
        lines = [f"[bold {GREEN}]#{batch.id} · {batch.name}[/]"] + report.summary_lines(batch)
        cfg = report.config_lines(batch)
        if cfg:
            lines += ["", f"[{GREEN_SOFT}]Configuração:[/]"] + [f"  {c}" for c in cfg]
        if batch.notes:
            lines += ["", f"Notas: {batch.notes}"]
        detail.update("\n".join(lines))
        only_warn = self.query_one("#b-only-warn", Switch).value
        for e in self.repo.events(batch.id, limit=3000):
            if only_warn and e.level not in LEVEL_STYLE:
                continue
            log_widget.write(Text(f"{e.ts[11:19]} {e.level[:4]} {e.message}", style=LEVEL_STYLE.get(e.level, GREEN_SOFT)))

    # -- eventos --------------------------------------------------------------
    @on(DataTable.RowHighlighted, "#b-table")
    def highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key is None or event.row_key.value is None:
            return
        new = int(event.row_key.value)
        if new != self.selected:
            self.selected = new
            self.confirm_delete = None
            self.query_one("#b-delete", Button).label = "Excluir"
            self.show_detail()

    @on(Switch.Changed, "#b-only-warn")
    @on(Button.Pressed, "#b-refresh")
    def reload(self) -> None:
        self.refresh_data()

    @on(Button.Pressed, "#b-run")
    def run_selected(self) -> None:
        batch = self.repo.get(self.selected) if self.selected is not None else None
        if batch is None:
            self.notify("Selecione um lote.", severity="warning")
        elif batch.remaining == 0:
            self.notify("Este lote já foi concluído.", severity="warning")
        else:
            self.app.start_batch(batch.id)  # type: ignore[attr-defined]

    @on(Button.Pressed, "#b-export")
    def export(self) -> None:
        if self.selected is None:
            self.notify("Selecione um lote.", severity="warning")
            return
        folder = report.export_batch(self.selected, self.app.repo, self.repo, ROOT / "exports")  # type: ignore[attr-defined]
        self.notify(f"Relatório salvo em {folder.relative_to(ROOT)}")

    @on(Button.Pressed, "#b-delete")
    def delete(self) -> None:
        button = self.query_one("#b-delete", Button)
        if self.selected is None:
            self.notify("Selecione um lote.", severity="warning")
        elif self.confirm_delete != self.selected:
            self.confirm_delete = self.selected
            button.label = "Confirmar exclusão?"
        else:
            self.repo.delete(self.selected)
            logging.getLogger("ui").info("Lote %s excluído (as contas ficam em Contas).", self.selected)
            self.selected = self.confirm_delete = None
            button.label = "Excluir"
            self.app.refresh_data()  # type: ignore[attr-defined]
            self.notify("Lote excluído. As contas continuam na aba Contas.")
