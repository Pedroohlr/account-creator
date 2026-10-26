"""Relatório de um lote: resumo em Markdown, contas em CSV e log completo."""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from ..ui.estimate import fmt_duration
from .batches import BatchEvent, BatchRecord, BatchRepository
from .repository import AccountRecord, AccountRepository

CONFIG_LABELS = {
    "per_device": "contas por dispositivo", "retries": "tentativas extras", "delay_between": "pausa entre contas (s)",
    "wipe_on_rotate": "limpar dados ao trocar", "random_user_agent": "User-Agent aleatório",
    "headless": "emulador sem janela", "mode": "proxy", "rotate_on_limit": "trocar IP ao ser limitado",
    "rotate_per_device": "trocar IP por dispositivo", "price_per_gb": "preço por GB",
}


def fmt_bytes(n: int) -> str:
    value = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{n} B"


def fmt_money(value: float, currency: str) -> str:
    return f"{currency} {value:,.4f}".replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_dt(value: str | None) -> str:
    return value.replace("T", " ") if value else "—"


def config_lines(batch: BatchRecord) -> list[str]:
    lines = []
    for section in batch.config.values():
        if isinstance(section, dict):
            for key, value in section.items():
                if key in CONFIG_LABELS:
                    shown = ("sim" if value else "não") if isinstance(value, bool) else value
                    lines.append(f"{CONFIG_LABELS[key]}: {shown}")
    return lines


def summary_lines(batch: BatchRecord) -> list[str]:
    rate = f"{batch.success_rate:.0f}%" if batch.success_rate is not None else "—"
    per_account = fmt_duration(batch.seconds_per_account) if batch.seconds_per_account else "—"
    lines = [
        f"Status: {batch.status}",
        f"Progresso: {batch.done} de {batch.target_count} (criadas {batch.created}, falhas {batch.failed}, taxa {rate})",
        f"Dispositivos usados: {batch.devices}",
        f"Tempo ativo: {fmt_duration(batch.active_seconds)}  ·  por conta: {per_account}",
        f"Esperas por limite do site: {batch.cooldowns} ({fmt_duration(batch.cooldown_seconds)})",
        f"Trocas de IP: {batch.rotations_ip}",
        f"Tráfego do proxy: {fmt_bytes(batch.total_bytes)} (↓ {fmt_bytes(batch.bytes_in)} · ↑ {fmt_bytes(batch.bytes_out)})",
        f"Custo: {fmt_money(batch.cost, batch.currency)}",
        f"Criado em: {fmt_dt(batch.created_at)}  ·  início: {fmt_dt(batch.started_at)}  ·  fim: {fmt_dt(batch.finished_at)}",
    ]
    if batch.error:
        lines.append(f"Erro: {batch.error}")
    return lines


def markdown(batch: BatchRecord, accounts: list[AccountRecord], events: list[BatchEvent]) -> str:
    out = [f"# Lote #{batch.id} — {batch.name}", ""]
    out += [f"- {line}" for line in summary_lines(batch)]
    cfg = config_lines(batch)
    if cfg:
        out += ["", "## Configuração do lote", ""] + [f"- {line}" for line in cfg]
    if batch.notes:
        out += ["", "## Notas", "", batch.notes]
    problems = [e for e in events if e.level in ("WARNING", "ERROR", "CRITICAL")]
    out += ["", f"## Avisos e erros ({len(problems)})", ""]
    out += [f"- `{e.ts[11:19]}` **{e.level}** {e.message}" for e in problems] or ["Nenhum."]
    failures = [a for a in accounts if a.status == "falhou"]
    out += ["", f"## Contas com falha ({len(failures)})", ""]
    out += [f"- {a.email}: {a.error}" for a in failures] or ["Nenhuma."]
    out += ["", f"_Gerado em {datetime.now():%Y-%m-%d %H:%M:%S}. As contas e o log completo estão nos CSV ao lado._", ""]
    return "\n".join(out)


def export_batch(batch_id: int, accounts: AccountRepository, batches: BatchRepository, out_root: Path) -> Path:
    """Grava a pasta do relatório e devolve o caminho."""
    batch = batches.get(batch_id)
    if batch is None:
        raise ValueError(f"Lote {batch_id} não existe.")
    folder = out_root / f"lote_{batch.id}_{datetime.now():%Y%m%d_%H%M%S}"
    folder.mkdir(parents=True, exist_ok=True)
    recs, events = accounts.list_for_batch(batch_id), batches.events(batch_id, limit=100000)
    (folder / "relatorio.md").write_text(markdown(batch, recs, events), encoding="utf-8")
    with (folder / "contas.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["id", "email", "senha", "status", "dispositivo", "duracao_s", "data", "erro"])
        for r in recs:
            w.writerow([r.id, r.email, r.password, r.status, r.device or "",
                        round(r.duration, 1) if r.duration else "", r.created_at, r.error or ""])
    with (folder / "log.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["hora", "nivel", "origem", "mensagem"])
        for e in events:
            w.writerow([e.ts, e.level, e.source, e.message])
    return folder
