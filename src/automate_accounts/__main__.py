"""Ponto de entrada: python -m automate_accounts <comando>."""
from __future__ import annotations

import argparse
import logging
import sys

from .config import ROOT, load_settings
from .core.driver import clear_browser_state
from .core.session import mobile_session
from .data.generator import generate_account
from .flows.create_account import AccountCreationError, CreateAccountFlow
from .logging_setup import setup_logging

log = logging.getLogger("cli")


def screenshot(driver, name: str) -> str:
    shots = ROOT / "screenshots"
    shots.mkdir(exist_ok=True)
    path = shots / f"{name}.png"
    driver.save_screenshot(str(path))
    return str(path)


def smoke() -> int:
    """Abre a página de login no Chrome do emulador e tira um screenshot."""
    settings = load_settings()
    try:
        with mobile_session(settings) as driver:
            driver.get(settings.target_url)
            shot = screenshot(driver, "smoke")
            print(f"OK: {driver.title!r} -> {driver.current_url}\nScreenshot: {shot}")
        return 0
    except Exception:
        log.exception("Smoke test falhou")
        return 1


def create_one() -> int:
    """Cria uma única conta de teste e imprime as credenciais."""
    settings = load_settings()
    data = generate_account()
    try:
        with mobile_session(settings) as driver:
            clear_browser_state(driver)
            try:
                CreateAccountFlow(driver, settings.target_url).run(data)
            except AccountCreationError as exc:
                print(f"FALHOU: {exc}\nScreenshot: {screenshot(driver, 'erro_create_one')}")
                return 1
            print(f"Conta criada: {data.email}\nSenha: {data.password}")
            print(f"Screenshot: {screenshot(driver, 'create_one')}")
        return 0
    except Exception:
        log.exception("create-one falhou")
        return 1


def menu() -> int:
    """Abre o menu interativo (padrão)."""
    from .ui.app import AccountsApp  # import tardio: Textual só é carregado quando necessário

    try:
        settings = load_settings()
    except RuntimeError as exc:
        print(f"Configuração incompleta: {exc}")
        print("Copie .env.example para .env e preencha.")
        return 1
    setup_logging(logging.INFO)  # só em arquivo: logs no terminal quebrariam a interface
    AccountsApp(settings).run()
    return 0


COMMANDS = {"menu": menu, "smoke": smoke, "create-one": create_one}


def main() -> int:
    parser = argparse.ArgumentParser(prog="automate-accounts")
    parser.add_argument(
        "command", choices=COMMANDS, nargs="?", default="menu",
        help="menu (padrão); smoke: valida a infraestrutura; create-one: cria uma conta",
    )
    args = parser.parse_args()

    if args.command != "menu":
        setup_logging(logging.INFO, logging.StreamHandler(sys.stderr))
    return COMMANDS[args.command]()


if __name__ == "__main__":
    sys.exit(main())
