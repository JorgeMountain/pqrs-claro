"""Coordina búsquedas por solicitud sin modificar la identificación confirmada."""

import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from langgraph.checkpoint.sqlite import SqliteSaver

from .service import user_error
from .source_assessment import OpenAISourceAssessor
from .source_graph import build_source_graph
from .source_library import digest
from .source_retrieval import retrieve
from .storage import Conflict, now


class SourceService:
    def __init__(self, settings, cases, library, *, assessor=None):
        self.settings, self.cases, self.library = settings, cases, library
        self.assessor = assessor
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sources")
        self.lock = threading.RLock()
        self.active = set()

    def inputs(self, case_id):
        with self.library.lock:
            case = self.cases.get(case_id)
            case["allowed_collection_ids"] = self.library.linked_collections(case_id)
            sources, chunks = self.library.snapshot(case_id)
            fingerprint = digest(
                {
                    "identification": case["identification"],
                    "sources": sources,
                    "model": self.settings.model,
                    "analysis_version": 6,
                    "collections": case["allowed_collection_ids"],
                }
            )
        return case, sources, chunks, fingerprint

    def get(self, case_id):
        case = self.cases.get(case_id)
        run = self.library.latest_run(case_id)
        sources = self.library.eligible(case_id)
        fingerprint = digest(
            {
                "identification": case["identification"],
                "sources": sources,
                "model": self.settings.model,
                "analysis_version": 6,
                "collections": self.library.linked_collections(case_id),
            }
        )
        if not run:
            return dict(
                status="idle",
                results=[],
                source_count=len(sources),
                searched_at=None,
                error=None,
                completed_count=0,
                total_count=case["request_count"],
                stale=False,
            )
        stale = run["fingerprint"] != fingerprint
        return {
            **run,
            "status": "stale" if stale and run["status"] != "running" else run["status"],
            "stale": stale,
            "source_count": len(sources),
        }

    def start(self, case_id, version):
        with self.lock:
            case, sources, chunks, fingerprint = self.inputs(case_id)
            if case["status"] != "confirmed":
                raise Conflict("Confirma primero las solicitudes identificadas.")
            if case["version"] != version:
                raise Conflict("El expediente cambió. Recarga antes de buscar fuentes.")
            if case_id in self.active:
                raise Conflict("La búsqueda de este expediente ya está en curso.")
            if not self.settings.api_key and self.assessor is None:
                raise ValueError(
                    "Falta configurar OpenAI para evaluar la pertinencia de las fuentes."
                )
            if not sources:
                raise ValueError(
                    "Carga al menos una norma o un soporte de este caso antes de buscar."
                )
            previous = self.library.latest_run(case_id)
            if (
                previous
                and previous["fingerprint"] == fingerprint
                and previous["status"] == "ready"
            ):
                return self.get(case_id)
            run = dict(
                id=uuid4().hex,
                case_id=case_id,
                status="running",
                fingerprint=fingerprint,
                results=[],
                source_count=len(sources),
                source_snapshot=sources,
                allowed_collection_ids=case["allowed_collection_ids"],
                searched_at=now(),
                error=None,
                completed_count=0,
                total_count=len(case["identification"]["requests"]),
                stale=False,
            )
            self.library.save_run(run)
            self.active.add(case_id)
            self.pool.submit(self.run, case, chunks, run)
            return self.get(case_id)

    def run(self, case, chunks, run):
        try:
            assessor = self.assessor or OpenAISourceAssessor(
                self.settings.api_key, self.settings.model
            )
            with SqliteSaver.from_conn_string(
                str(self.settings.data_dir / "source_checkpoints.sqlite")
            ) as saver:
                # El checkpoint conserva candidatos y resultados; no duplica la biblioteca
                # completa en cada paso de cada solicitud.
                graph = build_source_graph(
                    lambda request, _: retrieve(request, chunks), assessor, saver
                )
                for request in case["identification"]["requests"]:
                    request = {
                        **request,
                        "case_id": case["id"],
                        "allowed_collection_ids": run.get("allowed_collection_ids", []),
                    }
                    config = {
                        "configurable": {
                            "thread_id": f"{case['id']}:{request['id']}:{run['fingerprint']}"
                        }
                    }
                    try:
                        snapshot = graph.get_state(config)
                        if snapshot.values.get("finding") and not snapshot.next:
                            finding = snapshot.values["finding"]
                        else:
                            initial = (
                                None if snapshot.values else {"request": request, "chunks": []}
                            )
                            finding = graph.invoke(initial, config)["finding"]
                        run["results"].append(finding)
                    except Exception as exc:
                        run["results"].append(
                            dict(
                                request_id=request["id"],
                                status="error",
                                summary=user_error(exc),
                                supports=[],
                                missing=[],
                                warnings=[],
                            )
                        )
                    run["completed_count"] = len(run["results"])
                    self.library.save_run(run)
            errors = sum(f["status"] == "error" for f in run["results"])
            run.update(
                status="error" if errors else "ready",
                error=f"No se pudieron evaluar {errors} solicitudes. "
                "Reintenta para recuperar el avance."
                if errors
                else None,
            )
        except Exception as exc:
            run.update(status="error", error=user_error(exc))
        finally:
            self.library.save_run(run)
            with self.lock:
                self.active.discard(case["id"])

    def close(self):
        self.pool.shutdown(wait=True)
