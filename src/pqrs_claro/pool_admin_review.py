"""Handoff between the four human-reviewed workspaces and FIAGA's sequential queue."""

from langgraph.checkpoint.sqlite import SqliteSaver

from .models import Identification, Page, validate_identification, validate_pages
from .office_workspace import get_workspace
from .pool_drafts import _identified_row
from .pool_service import _admin
from .response_reading import open_gaps
from .storage import Conflict
from .workflow import build_graph


class PoolAdminReview:
    def __init__(self, pool, preanalysis, office):
        self.pool = pool
        self.preanalysis = preanalysis
        self.office = office

    def _restore_inputs(self, case_id, previous):
        pre = self.preanalysis
        case = pre.store.get(case_id)
        if pre.saved(case_id)["status"] != "idle" or case.get("identification"):
            return
        pre.original_matches(case_id, case["sha256"])
        path = pre.settings.data_dir / "checkpoints.sqlite"
        if not path.is_file():
            return
        with SqliteSaver.from_conn_string(str(path)) as saver:
            graph = build_graph(None, None, saver)
            # The former workflow kept its full, validated extraction in a case-specific graph.
            with saver.cursor(transaction=False) as cursor:
                threads = cursor.execute(
                    "SELECT thread_id FROM checkpoints WHERE thread_id GLOB ? AND checkpoint_ns='' "
                    "GROUP BY thread_id ORDER BY max(checkpoint_id) DESC",
                    (case_id + ":pool:*",),
                ).fetchall()
            for (thread,) in threads:
                if len(thread.split(":")) != 3:
                    continue
                values = graph.get_state({"configurable": {"thread_id": thread}}).values
                if not values.get("pages"):
                    continue
                pages = [Page.model_validate(page) for page in values["pages"]]
                validate_pages(pages)
                if values.get("identification"):
                    validate_identification(
                        Identification.model_validate(values["identification"]), pages
                    )
                    target = {"configurable": {"thread_id": case_id}}
                    if not graph.get_state(target).values:
                        graph.update_state(target, values, as_node="identify_requests")
                        graph.invoke(None, target)  # pause at the existing human review interrupt
                if previous.get("checks"):
                    pre.save(
                        case_id,
                        pre.saved(case_id),
                        status="ready",
                        check_version=(previous.get("reading") or {}).get("check_version"),
                        checks=previous["checks"],
                        pages=values["pages"],
                        page_count=len(pages),
                    )
                return

    def open(self, case_id, actor, revision):
        _admin(actor)
        with self.preanalysis.lock:
            previous = self.pool.get(case_id)
            if (
                previous["stage"] not in {"preparing", "initial_review"}
                or previous["revision"] != revision
            ):
                raise Conflict("El expediente cambió. Vuelve a abrir su revisión.")
            if previous["review_imported"]:
                raise Conflict("Este expediente ya pasó por la revisión administrativa.")
            self._restore_inputs(case_id, previous)
            return self.pool.open_admin_review(case_id, actor, revision)

    def submit(self, case_id, decision):
        _admin(decision.actor_id)
        review = self.office.reviews_service
        with self.preanalysis.lock, review.lock, self.office.library.lock:
            detail = self.pool.get(case_id)
            if detail["stage"] != "admin_review" or detail["revision"] != decision.revision:
                raise Conflict("El expediente cambió. Abre la versión vigente del borrador.")
            checked = self.preanalysis.require_approved(case_id)
            if checked["approval"]["actor_id"] != "admin":
                raise Conflict("Confirma el preanálisis con el perfil Administrador.")
            case = self.office.cases.get(case_id)
            if review.drafts_service.initial_review:
                review.drafts_service.initial_review.assert_allowed(case_id)
            result = review.get(case_id)
            reading = result["reading_confirmation"]
            if not reading["confirmed"] or (
                decision.content_hash and decision.content_hash != reading["content_hash"]
            ):
                raise Conflict(
                    "Confirma la lectura de las respuestas y sus faltantes actuales en Redacción."
                )
            workspace = get_workspace(self.office, case_id)
            if (
                decision.workspace_revision is not None
                and decision.workspace_revision != workspace["revision"]
            ):
                raise Conflict(
                    "El borrador fue modificado. Revisa su versión actual antes de entregarlo."
                )
            identification = case["identification"]
            source_map = review.sources_service.get(case_id)
            if source_map.get("scope_revoked") or len(identification["requests"]) != len(
                result["requests"]
            ):
                raise Conflict(
                    "Las fuentes o respuestas cambiaron. Actualiza la revisión antes de entregar."
                )
            findings = {r["request_id"]: r for r in source_map["results"]}
            rows = []
            for request, row in zip(identification["requests"], result["requests"], strict=True):
                if request["id"] != row["request_id"]:
                    raise Conflict(
                        "Las respuestas ya no corresponden a las peticiones confirmadas."
                    )
                finding = findings.get(request["id"])
                if finding is None:
                    raise Conflict(
                        "Las fuentes ya no corresponden a las peticiones confirmadas."
                    )
                cited = {key for p in row["paragraphs"] for key in p.get("cited_chunk_ids", [])}
                cited.update(s["chunk_id"] for s in finding.get("supports", []))
                gaps = open_gaps(row)
                rows.append(
                    {
                        **_identified_row(request),
                        "paragraphs": row["paragraphs"],
                        "facts": row.get("facts", []),
                        "sources": [s for s in row["available_supports"] if s["chunk_id"] in cited],
                        "answer": "\n\n".join(p["text"] for p in row["paragraphs"]),
                        "gap": "\n".join(gaps),
                        "gaps": gaps,
                        "source_status": finding["status"],
                        "source_summary": finding.get("summary", ""),
                        "secondary_source_checks": finding.get("secondary_source_checks", []),
                    }
                )
            snapshot = dict(
                text="\n\n".join(b["text"] for b in workspace["blocks"]),
                letter={
                    "blocks": workspace["blocks"],
                    "letterhead": workspace["letterhead"],
                    "metadata": workspace["metadata"],
                    "attachment_source_ids": workspace["attachment_source_ids"],
                },
                subject=workspace["metadata"]["subject"],
                requests=rows,
                checks=checked["checks"],
                reading={
                    "pages": [{k: v for k, v in p.items() if k != "text"} for p in checked["pages"]]
                },
                identification_warnings=identification.get("warnings", []),
                allowed_collection_ids=self.office.library.linked_collections(case_id),
            )
            return self.pool.import_admin_review(
                case_id, decision.actor_id, decision.revision, snapshot
            )
