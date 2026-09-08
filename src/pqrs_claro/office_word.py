"""Adaptador Word COM aislado; nunca conecta ni cierra la sesión Word del usuario."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

from .models import DomainError

WORD_TIMEOUT_SECONDS = 90


def _word_installed() -> bool:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"Word.Application\CLSID") as key:
            return bool(winreg.QueryValueEx(key, "")[0])
    except OSError:
        return False


def pdf_capabilities() -> dict:
    selected = os.environ.get("PQRS_CLARO_PDF_ENGINE", "auto").strip().casefold() or "auto"
    error = None
    if selected not in {"auto", "word"}:
        error = "El motor PDF configurado no es compatible. Configura PQRS_CLARO_PDF_ENGINE=word."
    elif sys.platform != "win32":
        error = "La conversión PDF requiere Windows y Microsoft Word en este equipo."
    elif not _word_installed():
        error = "No se encontró Microsoft Word. El PDF requiere Word instalado y disponible."
    else:
        try:
            available = importlib.util.find_spec("win32com.client") is not None
            available = available and importlib.util.find_spec("pythoncom") is not None
        except (ImportError, ModuleNotFoundError, ValueError):
            available = False
        if not available:
            error = (
                "Falta la dependencia pywin32 para convertir el oficio con Word. "
                "Ejecuta la instalación del proyecto."
            )
    return {
        "pdf_available": error is None,
        "pdf_engine": "word" if error is None else None,
        "error": error,
    }


def _terminate_owned_word(control: Path) -> None:
    """Un timeout solo puede terminar el proceso nuevo identificado por el worker."""
    try:
        import win32api
        import win32con
        import win32process

        value = json.loads(control.read_text(encoding="utf-8"))
        if value.get("owned") is not True or type(value.get("pid")) is not int:
            return
        handle = win32api.OpenProcess(
            win32con.PROCESS_QUERY_INFORMATION | win32con.PROCESS_TERMINATE, False, value["pid"]
        )
        try:
            created = str(win32process.GetProcessTimes(handle)["CreationTime"])
            if created == value.get("process_created"):
                win32api.TerminateProcess(handle, 1)
        finally:
            handle.Close()
    except Exception:
        # No se amplía la terminación a otros WINWORD si ya terminó o no se puede
        # demostrar que sea la instancia creada por esta operación.
        return


def convert_word(docx_path: Path, pdf_path: Path) -> str:
    capability = pdf_capabilities()
    if not capability["pdf_available"]:
        raise DomainError(capability["error"])
    docx_path, pdf_path = Path(docx_path).resolve(), Path(pdf_path).resolve()
    if not docx_path.is_file() or docx_path.suffix.casefold() != ".docx":
        raise DomainError("No se encontró el Word canónico que debe convertirse.")
    if pdf_path.exists():
        raise DomainError("La conversión no sobrescribe un PDF existente.")
    control = pdf_path.parent / ".word-worker.json"
    command = [
        sys.executable,
        "-m",
        "pqrs_claro.office_word",
        str(docx_path),
        str(pdf_path),
        str(control),
    ]
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError:
        raise DomainError("No se pudo iniciar el proceso de conversión con Word.") from None
    try:
        process.communicate(timeout=WORD_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        _terminate_owned_word(control)
        raise DomainError(
            "Word superó el tiempo máximo de 90 segundos. "
            "El oficio no quedó listo; vuelve a intentar."
        ) from None
    if process.returncode != 0 or not pdf_path.is_file() or pdf_path.stat().st_size == 0:
        _terminate_owned_word(control)
        raise DomainError(
            "Word no pudo convertir el documento a PDF. "
            "Comprueba que Word esté disponible y reintenta."
        )
    return "Microsoft Word COM"


def _worker(docx_path: Path, pdf_path: Path, control: Path) -> int:
    """Proceso propio STA. Los errores internos no se exponen en la API."""
    import pythoncom
    import win32api
    import win32com.client
    import win32con
    import win32process

    word = document = probe = None
    owned = False
    information = {"owned": False, "status": "starting"}

    def record():
        control.write_text(json.dumps(information), encoding="utf-8")

    pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)
    try:
        existing = set(win32process.EnumProcesses())
        word = win32com.client.DispatchEx("Word.Application")
        # Word expone Hwnd en Window, no en Application. Una ventana de un
        # documento temporal propio permite identificar la instancia COM exacta;
        # la diferencia entre listas de procesos por sí sola no prueba propiedad.
        probe = word.Documents.Add(Visible=False)
        _, pid = win32process.GetWindowThreadProcessId(probe.Windows.Item(1).Hwnd)
        if not pid or pid in existing:
            raise RuntimeError("Word did not provide an isolated process")
        handle = win32api.OpenProcess(win32con.PROCESS_QUERY_INFORMATION, False, pid)
        try:
            created = str(win32process.GetProcessTimes(handle)["CreationTime"])
        finally:
            handle.Close()
        owned = True
        information.update(owned=True, pid=pid, process_created=created, status="converting")
        record()
        probe.Close(SaveChanges=0)
        probe = None
        word.Visible = False
        word.DisplayAlerts = 0
        word.AutomationSecurity = 3  # msoAutomationSecurityForceDisable
        previous_links = word.Options.UpdateLinksAtOpen
        try:
            word.Options.UpdateLinksAtOpen = False
            document = word.Documents.Open(
                FileName=str(docx_path),
                ConfirmConversions=False,
                ReadOnly=True,
                AddToRecentFiles=False,
                Visible=False,
                OpenAndRepair=False,
                NoEncodingDialog=True,
            )
            document.Repaginate()
            document.ExportAsFixedFormat(
                OutputFileName=str(pdf_path),
                ExportFormat=17,
                OpenAfterExport=False,
                OptimizeFor=0,
                Range=0,
                Item=0,
                IncludeDocProps=False,
                KeepIRM=False,
                CreateBookmarks=1,
                DocStructureTags=True,
                BitmapMissingFonts=False,
                UseISO19005_1=False,
            )
        finally:
            word.Options.UpdateLinksAtOpen = previous_links
        information["status"] = "exported"
        record()
        return 0
    except Exception as exc:
        information.update(status="failed", error_type=type(exc).__name__)
        record()
        return 1
    finally:
        if probe is not None:
            try:
                probe.Close(SaveChanges=0)
            except Exception:
                pass
        if document is not None:
            try:
                document.Close(SaveChanges=0)
            except Exception:
                pass
        if word is not None and owned:
            try:
                word.Quit(SaveChanges=0)
            except Exception:
                pass
        probe = document = word = None
        pythoncom.CoUninitialize()


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit(2)
    raise SystemExit(_worker(*(Path(value).resolve() for value in sys.argv[1:])))
