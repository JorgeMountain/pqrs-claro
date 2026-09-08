"""Regresión de propiedad Word: HWND de la ventana propia, nunca Application.Hwnd."""

import json
import sys
from types import ModuleType, SimpleNamespace

import pytest

from pqrs_claro.office_word import _worker


@pytest.mark.parametrize("mode", ["isolated", "existing_process", "window_error"])
def test_worker_uses_own_temporary_window_and_closes_only_owned_objects(
    tmp_path, monkeypatch, mode
):
    events = []
    pid = 44

    class Window:
        @property
        def Hwnd(self):
            if mode == "window_error":
                raise AttributeError("Window unavailable in explicit test")
            events.append("window_hwnd")
            return 12345

    class Probe:
        Windows = SimpleNamespace(Item=lambda index: Window() if index == 1 else None)

        def Close(self, **kwargs):
            assert kwargs == {"SaveChanges": 0}
            events.append("probe_closed")

    class MainDocument:
        def Repaginate(self):
            events.append("repaginated")

        def ExportAsFixedFormat(self, **kwargs):
            assert kwargs["ExportFormat"] == 17
            events.append("exported")

        def Close(self, **kwargs):
            assert kwargs == {"SaveChanges": 0}
            events.append("document_closed")

    class Documents:
        def Add(self, **kwargs):
            assert kwargs == {"Visible": False}
            events.append("probe_created")
            return Probe()

        def Open(self, **kwargs):
            assert word.AutomationSecurity == 3 and word.Options.UpdateLinksAtOpen is False
            assert kwargs["ReadOnly"] is True and kwargs["Visible"] is False
            assert kwargs["AddToRecentFiles"] is False
            events.append("original_opened")
            return MainDocument()

    class Word:
        def __init__(self):
            self.Documents = Documents()
            self.Options = SimpleNamespace(UpdateLinksAtOpen=True)

        @property
        def Hwnd(self):
            pytest.fail("Word.Application.Hwnd no existe; utiliza una ventana del documento propio")

        def Quit(self, **kwargs):
            assert kwargs == {"SaveChanges": 0}
            events.append("word_quit")

    word = Word()
    package = ModuleType("win32com")
    client = ModuleType("win32com.client")
    client.DispatchEx = lambda name: word
    package.client = client
    monkeypatch.setitem(sys.modules, "win32com", package)
    monkeypatch.setitem(sys.modules, "win32com.client", client)
    monkeypatch.setitem(
        sys.modules,
        "pythoncom",
        SimpleNamespace(
            COINIT_APARTMENTTHREADED=2,
            CoInitializeEx=lambda mode: events.append("com_started"),
            CoUninitialize=lambda: events.append("com_closed"),
        ),
    )
    monkeypatch.setitem(sys.modules, "win32con", SimpleNamespace(PROCESS_QUERY_INFORMATION=1))
    monkeypatch.setitem(
        sys.modules,
        "win32api",
        SimpleNamespace(
            OpenProcess=lambda *args: SimpleNamespace(Close=lambda: events.append("handle_closed")),
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "win32process",
        SimpleNamespace(
            EnumProcesses=lambda: [pid] if mode == "existing_process" else [1, 2],
            GetWindowThreadProcessId=lambda hwnd: (99, pid),
            GetProcessTimes=lambda handle: {"CreationTime": "timestamp-of-owned-process"},
        ),
    )
    control = tmp_path / "control.json"
    result = _worker(tmp_path / "source.docx", tmp_path / "result.pdf", control)
    information = json.loads(control.read_text(encoding="utf-8"))
    assert events.count("probe_closed") == 1 and events[-1] == "com_closed"
    if mode == "isolated":
        assert result == 0 and information["owned"] is True
        assert information["pid"] == pid and information["status"] == "exported"
        assert information["process_created"] == "timestamp-of-owned-process"
        assert events.index("probe_closed") < events.index("original_opened")
        assert events.count("document_closed") == events.count("word_quit") == 1
        assert word.Options.UpdateLinksAtOpen is True
    else:
        assert result == 1 and information["owned"] is False
        assert "original_opened" not in events and "word_quit" not in events
        assert "Visible" not in word.__dict__ and "AutomationSecurity" not in word.__dict__
