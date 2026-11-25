"""Run the two drafting steps against a specific, durably recorded workflow revision."""

from concurrent.futures import ThreadPoolExecutor
from functools import partial
from threading import Lock
from uuid import uuid4

from .pool_progress import observe_progress
from .service import user_error
from .storage import Conflict


class PoolJobs:
    def __init__(self, pool, drafts):
        self.pool = pool
        self.drafts = drafts
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fiaga")
        self.lock = Lock()
        self.active = set()

    def schedule(self, case_id):
        state = self.pool.get(case_id)
        key = (case_id, state["stage"], state["revision"])
        if key[1] not in {"preparing", "integration"} or state.get("error"):
            return
        with self.lock:
            if key not in self.active:
                self.active.add(key)
                try:
                    self.executor.submit(self._run, *key)
                except Exception:
                    self.active.discard(key)
                    raise

    def _run(self, case_id, stage, revision):
        worker = uuid4().hex
        save = partial(self.pool.record_progress, case_id, stage, revision, worker)
        try:
            with observe_progress(stage, save):
                if stage == "preparing":
                    snapshot = self.drafts.initial(case_id)
                    self.pool.set_initial(case_id, snapshot, revision=revision, worker=worker)
                else:
                    current, previous, tasks = self.pool.integration_input(case_id)
                    if current == revision:
                        snapshot = self.drafts.integrate(case_id, previous, tasks)
                        self.pool.set_integrated(case_id, snapshot, revision=revision,
                                                 worker=worker)
        except Exception as exc:
            try:
                self.pool.set_error(case_id, user_error(exc), revision=revision, worker=worker)
            except (Conflict, KeyError):
                # Another revision owns the result, including its error message.
                pass
        finally:
            with self.lock:
                self.active.discard((case_id, stage, revision))

    def recover(self):
        scheduled = set()
        for job in self.pool.pending_jobs():
            if job["stage"] == "integration" and not job.get("error"):
                self.schedule(job["case_id"])
                scheduled.add(job["case_id"])
        self.pool.recover_orphaned_progress(scheduled)

    def close(self):
        self.executor.shutdown(wait=True, cancel_futures=True)
