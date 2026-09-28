"""Recoverable deletion, serialized against the application's running work."""
from contextlib import ExitStack

from fastapi import APIRouter
from pydantic import Field, StrictBool

from .case_purge import purge_case
from .models import StrictModel
from .storage import Conflict


class CaseAction(StrictModel):
    version: int = Field(ge=1)
    lifecycle_revision: int = Field(ge=0)
    management_revision: int = Field(default=0, ge=0)
    confirmed: StrictBool


def case_busy(case_id, services):
    return any(
        any((key[0] if isinstance(key, tuple) else key) == case_id
            for key in tuple(getattr(service, "active", ())))
        for service in services
    )


def lifecycle_router(store, services):
    router = APIRouter()

    def change(case_id, body, deleted, permanent=False):
        if not body.confirmed:
            raise ValueError("Confirma la acción sobre el expediente seleccionado.")
        # Nonblocking acquisition avoids lock-order deadlocks with existing workers.
        # Holding every admission lock closes the check/start race before deletion.
        with ExitStack() as stack:
            for service in services:
                if not service.lock.acquire(blocking=False):
                    raise Conflict("Hay una operación en curso. Espera un momento y reintenta.")
                stack.callback(service.lock.release)
            if case_busy(case_id, services):
                raise Conflict("Este expediente está procesándose. Espera a que termine.")
            if permanent:
                return purge_case(store, case_id, body.version, body.lifecycle_revision,
                                  body.management_revision)
            return store.set_deleted(case_id, version=body.version,
                                     lifecycle_revision=body.lifecycle_revision, deleted=deleted,
                                     management_revision=body.management_revision)

    @router.delete("/api/cases/{case_id}")
    def delete(case_id: str, body: CaseAction):
        return change(case_id, body, True)

    @router.post("/api/cases/{case_id}/restore")
    def restore(case_id: str, body: CaseAction):
        return change(case_id, body, False)

    @router.delete("/api/cases/{case_id}/permanent")
    def permanent(case_id: str, body: CaseAction):
        return change(case_id, body, True, permanent=True)

    return router
