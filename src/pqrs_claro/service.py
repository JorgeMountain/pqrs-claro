"""Opera el grafo y proyecta sus resultados a un expediente versionado."""

import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from .config import Settings
from .extraction import OpenAIOCR, PDFExtractor
from .identification import OpenAIIdentifier
from .models import Identification, Page, validate_identification
from .storage import CaseStore, Conflict, now
from .workflow import build_graph


def user_error(exc):
    """Los mensajes de proveedores pueden contener datos: devolver solo categorías seguras."""
    name = type(exc).__name__
    if name == "AuthenticationError":
        return "OpenAI rechazó la clave configurada. Revise su configuración y vuelva a intentar."
    if name == "RateLimitError":
        return "OpenAI no está disponible por límite de uso. El avance está guardado."
    if name in {"APITimeoutError", "APIConnectionError"}:
        return "No se pudo completar la conexión con OpenAI. Puede volver a intentar."
    if name == "ValidationError":
        return "La identificación no cumplió el formato esperado. Revise el documento y reintente."
    if isinstance(exc, ValueError):
        return str(exc)[:600]
    return "El proceso no pudo terminar. El avance está guardado; vuelva a intentar."


class CaseService:
    def __init__(self, settings: Settings, store: CaseStore, *, extractor=None, identifier=None):
        self.settings = settings
        self.store = store
        self.extractor = extractor
        self.identifier = identifier
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pqrs")
        self.lock = threading.RLock()
        self.active = set()
        self.initial_review = None
        self.management = None

    def graph(self, saver):
        extractor = self.extractor or PDFExtractor(
            ocr_provider=OpenAIOCR(self.settings.api_key, self.settings.model)
        )
        identifier = self.identifier or OpenAIIdentifier(self.settings.api_key, self.settings.model)
        return build_graph(extractor, identifier, saver)

    def start(self, case_id):
        with self.lock:
            case = self.store.get(case_id)
            if self.management:
                self.management.require_started(case_id)
            if case_id in self.active or case["status"] not in {"uploaded", "error"}:
                raise Conflict("Este expediente ya se está procesando o está listo para revisar.")
            if not self.settings.api_key and self.identifier is None:
                raise ValueError(
                    "Falta configurar OpenAI. No se realizará una identificación simulada."
                )
            self.active.add(case_id)
            case = self.store.update(
                case_id,
                status="reading",
                error=None,
                event="Análisis solicitado. El original permanece guardado.",
            )
            self.pool.submit(self.run, case_id)
            return case

    def run(self, case_id):
        config = {"configurable": {"thread_id": case_id}}
        try:
            pdf_path = self.store.original(case_id)
            if (
                hashlib.sha256(pdf_path.read_bytes()).hexdigest()
                != self.store.get(case_id)["sha256"]
            ):
                raise ValueError("El archivo original cambió en disco. Cargue nuevamente el PDF.")
            with SqliteSaver.from_conn_string(
                str(self.settings.data_dir / "checkpoints.sqlite")
            ) as saver:
                graph = self.graph(saver)
                snapshot = graph.get_state(config)
                if snapshot.values.get("confirmed"):
                    self.project(case_id, snapshot.values, confirmed=True)
                    return
                if (
                    snapshot.values.get("identification")
                    and "review_identification" in snapshot.next
                ):
                    # La revisión editable vive en el expediente hasta su confirmación.
                    # Reanudar no debe recuperar un borrador anterior sobre una corrección.
                    saved = self.store.get(case_id).get("identification")
                    values = dict(snapshot.values)
                    if saved:
                        values["identification"] = saved
                    self.project(case_id, values)
                    return
                initial = (
                    None if snapshot.values else {"case_id": case_id, "pdf_path": str(pdf_path)}
                )
                for update in graph.stream(initial, config, stream_mode="updates"):
                    if "read_pdf" in update:
                        values = update["read_pdf"]
                        self.store.update(
                            case_id,
                            pages=values["pages"],
                            status="identifying",
                            event="Texto extraído por página. Identificando solicitudes.",
                        )
                    if "identify_requests" in update:
                        self.store.update(
                            case_id,
                            identification=update["identify_requests"]["identification"],
                            event="Solicitudes identificadas con referencias al original.",
                        )
                snapshot = graph.get_state(config)
                self.project(
                    case_id, snapshot.values, confirmed=bool(snapshot.values.get("confirmed"))
                )
        except Exception as exc:
            self.store.update(
                case_id,
                status="error",
                error=user_error(exc),
                event=f"Proceso detenido: {type(exc).__name__}. Avance conservado.",
            )
        finally:
            with self.lock:
                self.active.discard(case_id)

    def project(self, case_id, values, *, confirmed=False):
        with self.lock:
            case = self.store.update(
                case_id,
                pages=values.get("pages", []),
                identification=values.get("identification"),
                status="confirmed" if confirmed else "needs_review",
                error=None,
                confirmed_at=now() if confirmed else None,
                event=(
                    "Identificación confirmada. Primera entrega completada."
                    if confirmed
                    else "Lista para contrastar las solicitudes con el documento original."
                ),
            )
            if not confirmed and self.initial_review is not None:
                self.initial_review.analyze_identified(case)
            return case

    def save(self, case_id, version, identification):
        with self.lock:
            case = self.store.get(case_id)
            if case["status"] != "needs_review":
                raise Conflict("Solo puede editar una identificación pendiente de revisión.")
            if self.initial_review is not None and case_id in self.initial_review.active:
                raise Conflict("Espera a que termine el análisis del trámite antes de corregir.")
            pages = [Page.model_validate(p) for p in case["pages"]]
            result = Identification.model_validate(identification)
            validate_identification(result, pages)
            previous_identification = case["identification"]
            case = self.store.update(
                case_id,
                expected=version,
                identification=result.model_dump(mode="json"),
                event="Corrección guardada. Se conserva la versión anterior.",
            )
            if self.initial_review is not None:
                if not self.initial_review.reuse_selection(case, previous_identification):
                    self.initial_review.analyze_identified(case)
            return case

    def confirm(self, case_id, version):
        with self.lock:
            case = self.store.get(case_id)
            if case["version"] != version:
                raise Conflict("El expediente cambió. Recargue antes de confirmar.")
            if case["status"] != "needs_review":
                raise Conflict("La identificación todavía no está disponible para confirmar.")
            identification = Identification.model_validate(case["identification"])
            validate_identification(identification, [Page.model_validate(p) for p in case["pages"]])
            self.store.update(
                case_id,
                expected=version,
                status="confirming",
                event="Confirmación de la identificación solicitada.",
            )
            try:
                with SqliteSaver.from_conn_string(
                    str(self.settings.data_dir / "checkpoints.sqlite")
                ) as saver:
                    graph = self.graph(saver)
                    result = graph.invoke(
                        Command(resume=identification.model_dump(mode="json")),
                        {"configurable": {"thread_id": case_id}},
                    )
                if not result.get("confirmed"):
                    raise ValueError("La identificación aún necesita revisión.")
                return self.project(case_id, result, confirmed=True)
            except Exception as exc:
                self.store.update(
                    case_id,
                    status="error",
                    error=user_error(exc),
                    event="No se completó la confirmación. Correcciones conservadas.",
                )
                raise ValueError(user_error(exc)) from None

    def close(self):
        self.pool.shutdown(wait=True)
