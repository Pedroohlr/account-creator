"""Verificações de saúde do ambiente: tudo que precisa estar pronto antes de criar contas."""
from __future__ import annotations

import ctypes
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

from ..config import Settings
from ..data.repository import AccountRepository

OK, WARN, FAIL = "ok", "warn", "fail"


@dataclass(frozen=True)
class Check:
    name: str
    level: str          # ok | warn | fail
    detail: str
    hint: str = ""

    @property
    def ok(self) -> bool:
        return self.level != FAIL


def free_ram_gb() -> float | None:
    """RAM física livre em GB (Windows); None se não for possível medir."""
    if sys.platform != "win32":
        return None

    class MemStatus(ctypes.Structure):
        _fields_ = [
            ("length", ctypes.c_ulong), ("load", ctypes.c_ulong),
            ("total_phys", ctypes.c_ulonglong), ("avail_phys", ctypes.c_ulonglong),
            ("total_page", ctypes.c_ulonglong), ("avail_page", ctypes.c_ulonglong),
            ("total_virt", ctypes.c_ulonglong), ("avail_virt", ctypes.c_ulonglong),
            ("avail_ext", ctypes.c_ulonglong),
        ]

    status = MemStatus()
    status.length = ctypes.sizeof(MemStatus)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    return status.avail_phys / 1024**3


def _run(cmd: list[str], timeout: float = 25) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    return (result.stdout + result.stderr).strip()


# -- verificações individuais ----------------------------------------------
def check_python(_s: Settings) -> Check:
    v = sys.version_info
    ok = v >= (3, 11)
    return Check("Python", OK if ok else FAIL, f"{v.major}.{v.minor}.{v.micro}",
                 "" if ok else "Use Python 3.11 ou superior.")


def check_sdk(s: Settings) -> Check:
    missing = [p.name for p in (s.adb, s.emulator_bin) if not p.exists()]
    if missing:
        return Check("Android SDK", FAIL, f"faltando: {', '.join(missing)}",
                     "Instale o SDK pelo Android Studio e/ou defina ANDROID_HOME no .env.")
    return Check("Android SDK", OK, str(s.android_home))


def check_avd(s: Settings) -> Check:
    if not s.emulator_bin.exists():
        return Check("AVD (emulador)", FAIL, "emulator.exe não encontrado")
    avds = _run([str(s.emulator_bin), "-list-avds"], 30).splitlines()
    if s.avd_name in avds:
        return Check("AVD (emulador)", OK, s.avd_name)
    return Check("AVD (emulador)", FAIL, f"'{s.avd_name}' não existe (há: {', '.join(avds) or 'nenhum'})",
                 "Crie o AVD no Device Manager do Android Studio ou escolha outro em Configurações.")


def check_acceleration(s: Settings) -> Check:
    if not s.emulator_bin.exists():
        return Check("Aceleração (WHPX/HAXM)", FAIL, "emulator.exe não encontrado")
    out = _run([str(s.emulator_bin), "-accel-check"], 20)
    if "usable" in out.lower() and "not" not in out.lower().split("usable")[0][-12:]:
        return Check("Aceleração (WHPX/HAXM)", OK, out.splitlines()[-1][:80])
    return Check("Aceleração (WHPX/HAXM)", WARN, (out.splitlines() or ["indisponível"])[-1][:80],
                 "Sem aceleração o emulador fica muito lento. Ative Hyper-V/WHPX no Windows.")


def check_java(_s: Settings) -> Check:
    if not shutil.which("java"):
        return Check("Java (JDK)", WARN, "não encontrado no PATH", "O Appium usa o JDK para o adb/apksigner.")
    out = _run(["java", "-version"], 15).splitlines()
    return Check("Java (JDK)", OK, out[0][:70] if out else "ok")


def check_node(_s: Settings) -> Check:
    if not shutil.which("node"):
        return Check("Node.js", FAIL, "não encontrado", "Instale o Node.js (nodejs.org).")
    return Check("Node.js", OK, _run(["node", "--version"], 10))


def check_appium(_s: Settings) -> Check:
    exe = shutil.which("appium")
    if not exe:
        return Check("Appium", FAIL, "não encontrado", "npm i -g appium")
    return Check("Appium", OK, _run([exe, "--version"], 30).splitlines()[-1])


def check_appium_driver(_s: Settings) -> Check:
    exe = shutil.which("appium")
    if not exe:
        return Check("Driver UiAutomator2", FAIL, "Appium ausente")
    out = _run([exe, "driver", "list", "--installed"], 40)
    line = next((ln for ln in out.splitlines() if "uiautomator2" in ln), None)
    if line:
        return Check("Driver UiAutomator2", OK, line.strip(" -√✔").split("[")[0].strip())
    return Check("Driver UiAutomator2", FAIL, "não instalado", "appium driver install uiautomator2")


def check_ram(_s: Settings) -> Check:
    gb = free_ram_gb()
    if gb is None:
        return Check("Memória RAM livre", WARN, "não foi possível medir")
    detail = f"{gb:.1f} GB livres"
    if gb < 1.5:
        return Check("Memória RAM livre", WARN, detail,
                     "Pouca RAM: feche o navegador e outros programas. Tudo fica bem mais lento.")
    return Check("Memória RAM livre", OK, detail)


def check_site(s: Settings) -> Check:
    try:
        with urllib.request.urlopen(s.target_url, timeout=10) as r:
            return Check("Site de homologação", OK, f"HTTP {r.status}")
    except urllib.error.HTTPError as exc:
        return Check("Site de homologação", WARN, f"HTTP {exc.code}")
    except (urllib.error.URLError, OSError) as exc:
        return Check("Site de homologação", FAIL, str(getattr(exc, "reason", exc))[:70],
                     "Confira a URL em Configurações e sua conexão.")


def check_database(_s: Settings) -> Check:
    try:
        counts = AccountRepository().counts()
    except Exception as exc:  # banco corrompido/sem permissão
        return Check("Banco de dados", FAIL, str(exc)[:70])
    return Check("Banco de dados", OK, f"{counts['criada']} criadas · {counts['falhou']} falhas")


CHECKS: list[tuple[str, Callable[[Settings], Check]]] = [
    ("Python", check_python),
    ("Android SDK", check_sdk),
    ("AVD (emulador)", check_avd),
    ("Aceleração (WHPX/HAXM)", check_acceleration),
    ("Java (JDK)", check_java),
    ("Node.js", check_node),
    ("Appium", check_appium),
    ("Driver UiAutomator2", check_appium_driver),
    ("Memória RAM livre", check_ram),
    ("Site de homologação", check_site),
    ("Banco de dados", check_database),
]


def run_check(name: str, fn: Callable[[Settings], Check], settings: Settings) -> Check:
    """Executa uma verificação sem deixar exceção inesperada derrubar o painel."""
    try:
        return fn(settings)
    except subprocess.TimeoutExpired:
        return Check(name, WARN, "tempo esgotado ao verificar")
    except Exception as exc:
        return Check(name, FAIL, f"erro inesperado: {exc}"[:80])
