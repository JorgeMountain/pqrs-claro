"""OCR de Windows instalado en el equipo; no envía documentos a servicios externos."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from .models import DomainError


class WindowsOCR:
    """Worker local reutilizable. Cada transcripción sigue necesitando revisión humana."""

    def __init__(self, language="es-ES", timeout=45.0):
        self.language = language
        self.timeout = timeout
        self.capabilities = {}
        self._process = None
        self._responses = queue.Queue()
        self._lock = threading.RLock()

    def _start(self):
        if self._process is not None and self._process.poll() is None:
            return
        if os.name != "nt":
            raise DomainError(
                "El OCR local requiere Windows con reconocimiento de texto instalado."
            )
        self._responses = queue.Queue()
        self._process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "pqrs_claro.windows_ocr_worker",
                self.language,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            encoding="utf-8",
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        responses = self._responses
        process = self._process

        def read_responses():
            try:
                for line in process.stdout:
                    responses.put(line)
            finally:
                responses.put(None)

        threading.Thread(target=read_responses, daemon=True).start()
        ready = self._receive()
        if not ready.get("ready"):
            self.close()
            raise DomainError(ready.get("error") or "No se pudo iniciar el OCR local.")
        self.capabilities = ready

    def _receive(self):
        try:
            line = self._responses.get(timeout=self.timeout)
        except queue.Empty:
            self.close()
            raise DomainError("El OCR local excedió el tiempo máximo; la página quedó pendiente.")
        if line is None:
            self.close()
            raise DomainError("El proceso de OCR local terminó sin devolver una transcripción.")
        try:
            result = json.loads(line)
            if not isinstance(result, dict):
                raise ValueError
            return result
        except (ValueError, TypeError):
            self.close()
            raise DomainError("El OCR local devolvió una respuesta inválida.") from None

    def probe(self):
        with self._lock:
            self._start()
            return dict(self.capabilities)

    def __call__(self, png_bytes):
        with self._lock:
            self._start()
            with tempfile.TemporaryDirectory(prefix="pqrs-ocr-") as folder:
                path = Path(folder) / "page.png"
                path.write_bytes(png_bytes)
                try:
                    self._process.stdin.write(json.dumps({"path": str(path)}) + "\n")
                    self._process.stdin.flush()
                    result = self._receive()
                except DomainError:
                    raise
                except (OSError, ValueError):
                    self.close()
                    raise DomainError("No se pudo comunicar con el OCR local.") from None
            if not result.get("ok"):
                raise DomainError(result.get("error") or "No se pudo leer la página con OCR local.")
            text = result.get("text")
            if not isinstance(text, str):
                raise DomainError("El OCR local no devolvió texto válido.")
            return text

    def close(self):
        with self._lock:
            process, self._process = self._process, None
            if process is None:
                return
            if process.stdin:
                try:
                    process.stdin.close()
                except OSError:
                    pass
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
            if process.stdout:
                process.stdout.close()

    def __enter__(self):
        self.probe()
        return self

    def __exit__(self, *_):
        self.close()
