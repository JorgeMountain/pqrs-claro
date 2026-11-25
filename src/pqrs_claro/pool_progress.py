"""Report work as it runs, including concurrent requests in a single pool job."""

from contextlib import contextmanager
from contextvars import ContextVar
from threading import Lock

_observer = ContextVar("pool_progress", default=None)


class JobProgress:
    def __init__(self, stage, save):
        self.save = save
        self.lock = Lock()
        self.steps = dict.fromkeys(("reading", "checks", "identification", "library"), "pending")
        self.requests = {}
        self.stage = "preanalysis" if stage == "preparing" else "integration"

    def persist(self, *, begin=False, output=None):
        kwargs = {"output": output} if output is not None else {}
        self.save(dict(stage=self.stage, status="running", steps=self.steps,
                       requests=list(self.requests.values())), begin=begin, **kwargs)


@contextmanager
def observe_progress(stage, save):
    progress = JobProgress(stage, save)
    progress.persist(begin=True)
    token = _observer.set(progress)
    try:
        yield
    finally:
        _observer.reset(token)


def report_requests(requests):
    progress = _observer.get()
    if progress is None:
        return
    with progress.lock:
        progress.requests = {
            r["id"]: dict(id=r["id"], label=r.get("title") or r.get("text") or r["id"],
                          sources="pending", drafting="pending", integration="pending")
            for r in requests
        }
        progress.persist()


def report_step(name, status, request_id=None, *, result=None):
    progress = _observer.get()
    if progress is None:
        return
    with progress.lock:
        target = progress.steps if request_id is None else progress.requests[request_id]
        target[name] = status
        output = (name, request_id or "", result) if result is not None else None
        progress.persist(output=output)


@contextmanager
def progress_step(name, request_id=None):
    report_step(name, "running", request_id)
    result = {}
    try:
        yield result
    except Exception:
        report_step(name, "error", request_id)
        raise
    else:
        report_step(name, "done", request_id, result=result or None)
