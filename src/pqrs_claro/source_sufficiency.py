"""Suficiencia por afirmación y uso, sin certificar documentos ni aprobar respuestas.

La cobertura es una evaluación atribuida al modelo. Python verifica sus vínculos
literales y limita su efecto: solo las advertencias de catálogo que no afectan al
contenido consultado dejan de convertirse en requisitos de evidencia.
"""

from __future__ import annotations

import re
import unicodedata

from .models import DomainError
from .request_intent import classify_request_intent
from .request_requirements import validate_requirement_checks
from .source_documents import available_copy_matches
from .source_uncertainties import validated_uncertainties

POLICY_VERSION = 9

DOCUMENT_STATE_GUIDANCE = """
document_states separa tres dimensiones locales: availability=identified_copy
identifica el archivo almacenado solicitado; authenticity=not_inferred_from_availability
no certifica autenticidad ni integridad respecto de un original externo; delivery=pending
conserva la entrega futura. No infieras firma, certificación, anexos completos ni envío.
Para ofrecer una copia común identificada, review_status pendiente por sí solo es una
observación, no un impedimento. Conserva los cotejos concretos de identidad, contenido,
transcripción, versión o autenticidad expresamente solicitada. Una entrega pasada
consultada necesita su propia evidencia. Los estados no resuelven comprobaciones humanas.
Certificar la autenticidad de una copia no establece la vigencia de su norma. Pedir
una copia certificada no exige por sí solo comprobar vigencia o aplicación jurídica.
Conserva ese control si se pregunta por vigencia, derogación, efectos o aplicación
de la norma, incluso en un periodo histórico, o si existe una brecha concreta.
Identificar al firmante, cotejar la firma o reconstruir la procedencia e ingreso
del archivo son comprobaciones documentales; no preguntan por sí solas si la norma
está vigente. «La firma corresponde a esa persona» expresa identidad, no un derecho
o aplicación de la norma. Mantén pendientes esos cotejos cuando falte su evidencia.
Un cotejo concreto pendiente de autenticidad del mismo archivo y versión ya incluye
su procedencia: no añadas otra tarea genérica por review_status. Conserva separados
los cotejos materiales distintos y la certificación o entrega futuras. Agrupar una
redundancia no significa resolver ni aprobar el cotejo de autenticidad.
"""

COVERAGE_USES_BY_ROLE = {
    "rule": ["rule", "attributed_content"],
    "antecedent": ["attributed_content"],
    "historical_evidence": ["attributed_content", "verified_fact", "official_status"],
    "document": ["attributed_content", "document_delivery", "official_status"],
    "fact": ["attributed_content", "verified_fact", "official_status"],
}


def coverage_uses(source, role):
    uses = COVERAGE_USES_BY_ROLE.get(role, [])
    if source.get("category") in {"national_norm", "institutional_norm"}:
        permitted = [use for use in uses if use not in {"verified_fact", "official_status"}]
        # The requested original can also contain a rule to explain. Keep one
        # literal support instead of duplicating its chunk under conflicting roles.
        if role == "document":
            permitted.append("rule")
        return permitted
    return uses


def _plain(text):
    return " ".join("".join(
        c for c in unicodedata.normalize("NFKD", str(text).casefold())
        if not unicodedata.combining(c)
    ).split())


def _literal(text):
    return " ".join(unicodedata.normalize("NFC", text).split())


def _positive_copy_requirements(texts):
    retained = []
    for text in texts:
        for clause in re.split(
            r"[,.;!?]+|\b(?:pero|sino|solo|solamente|unicamente|sin embargo|no obstante)\b|"
            r"\by\s+si\b|"
            r"\by\s+(?=(?:solicito|requiero|pido|necesito|confirme|verifique)\b)",
            _plain(text),
        ):
            # Only an explicit negative mandate, never 'confirme que no fue firmado'.
            negative = re.search(
                r"(?:^|,\s*)\s*no\s+(?:solicito|requiero|pido|necesito|exijo)\b", clause)
            retained.append(clause[:negative.start()] if negative else clause)
    return ". ".join(retained)


def _copy_scope_texts(request):
    from .source_context import _scope_quotes

    context = request.get("context") or {}
    scope = _scope_quotes(context.get("document_context") or {})
    texts = [request.get("description") or request.get("title") or "", *scope]
    # A parent's explicit qualification also governs the copied child request.
    texts.extend(row.get("description", "") for row in context.get("ancestors", []))
    return texts


def _copy_authentication_requested(request):
    if classify_request_intent(request)["certification_requested"]:
        return True
    return bool(re.search(
        r"\b(?:autenticidad|autenticacion|autenticar|certificad[ao]s?|autenticad[ao]s?|"
        r"autentic[ao]s?|firmad[ao]s?|suscrit[ao]s?|certificacion|legalizad[ao]s?)\b|"
        r"\b(?:version|copia)\s+(?:oficial|expedida)\b|\bcon\s+firma\b|"
        r"\bconstancia\s+de\s+expedicion\b",
        _positive_copy_requirements(_copy_scope_texts(request))))


def document_delivery_states(request, sources):
    """Three independent dimensions, derived locally rather than by the reader.

    Availability describes the stored file only. Neither its hash nor a reviewed
    catalog entry establishes certification, completeness against an external
    original, or dispatch. Existing concrete checks retain their own resolution.
    """
    intent = classify_request_intent(request)
    if not intent["document_delivery_requested"]:
        return {}
    authentication_requested = _copy_authentication_requested(request)
    states = {}
    for source in sources:
        sid = source.get("source_id")
        if not sid:
            continue
        identified = available_copy_matches(request, source)
        if sid in states and states[sid]["availability"] == "identified_copy":
            continue
        states[sid] = {
            "availability": "identified_copy" if identified else "candidate_only",
            "authentication_requested": authentication_requested,
            "authenticity": "not_inferred_from_availability",
            "delivery": "pending",
        }
    return states


def coverage_citation_errors(selection, candidates):
    """Diagnóstico para un único reintento; nunca acepta ni reescribe citas."""
    index = {item["chunk_id"]: item for item in candidates}
    selected = {item.chunk_id for item in selection.supports}
    errors = []
    for aspect_index, item in enumerate(selection.coverage):
        for citation in item.citations:
            candidate = index.get(citation.chunk_id)
            if candidate is None:
                reason = "unknown_candidate"
            elif citation.chunk_id not in selected:
                reason = "candidate_not_selected_in_supports"
            elif (not _literal(citation.quote)
                  or _literal(citation.quote) not in _literal(candidate["quote"])):
                reason = "quote_not_literal_in_candidate"
            else:
                continue
            error = {"aspect_index": aspect_index, "chunk_id": citation.chunk_id,
                     "reason": reason}
            if reason == "quote_not_literal_in_candidate":
                error.update(submitted_quote=citation.quote, candidate_quote=candidate["quote"])
            errors.append(error)
    return errors


_SCOPE_DECISION = (
    r"(?:determin(?:ar|e[n]?)|decid(?:ir|a[n]?)|resolv(?:er|amos)|resuelv(?:a[n]?)|"
    r"establec(?:er)|establezc(?:a[n]?)|evalu(?:ar|e[n]?)|pronunci(?:arse|e[n]?se))"
)
_POSITIVE_MANDATE = (
    r"(?:solicito|pido|necesito|quiero|determinen?|decidan?|resuelvan?|"
    r"establezcan?|evaluen?|informen?|indiquen?|confirmen?|expliquen?|"
    r"aclaren?|precisen?|describan?|detallen?|enumeren?|respondan?|senalen?|"
    r"certifiquen?|verifiquen?|faciliten?|entreguen?)"
)


def _application_request_text(text):
    """Exclude a negated decision mandate, never a question about a negative fact.

    The exclusion stops at sentence/contrast boundaries or another affirmative
    mandate. A quoted rule or an unrecognised negation stays conservative.
    """
    clauses = re.split(
        rf"[.;!?¿]+|\b(?:pero|sin embargo|no obstante|ademas|aunque)\b|"
        rf"(?:\b(?:y|e)\s+|,\s*)(?=(?:si\s+)?{_POSITIVE_MANDATE}\b)", text)
    retained = []
    for clause in clauses:
        # Do not erase the object of an explanatory question: asking why someone
        # did not decide applicability is still a request about current facts.
        if re.match(r"^[\s¿]*(?:por que|como|cuando|quien|explique[n]?|informe[n]?)\b", clause):
            retained.append(clause)
            continue
        exclusion = re.search(
            rf"\b(?:no\s+(?:se\s+)?{_SCOPE_DECISION}|"
            rf"no\s+(?:(?:le|les)\s+)?(?:solicito|pido|requiero|necesito|deseo)\s+"
            rf"(?:que\s+(?:se\s+)?)?{_SCOPE_DECISION}|"
            rf"sin\s+{_SCOPE_DECISION})\b", clause)
        retained.append(clause[:exclusion.start()] if exclusion else clause)
    return ". ".join(retained)


def _requests_current_application(request):
    text = _plain(request.get("description") or request.get("title") or "")
    text = _positive_copy_requirements([text])
    text = _application_request_text(text)
    return bool(re.search(
        r"\b(?:actualmente|hoy|en la actualidad|este semestre|autenticidad|"
        r"version (?:oficial|expedida|firmada)|copia (?:oficial|autentica|certificada)|"
        r"vigentes?|para mi caso|tengo derecho|"
        r"puedo|podemos|debo|debemos|me corresponde|me aplica)\b",
        text,
    ))


def _requires_more_than_attribution(request):
    return (classify_request_intent(request)["intents"] != ["information"]
            or _requests_current_application(request))


def _documentary_copy_scope(text):
    """Interpret documentary checks only for the catalog-validity decision.

    This never changes the request, its global intent, or its concrete gaps.
    Unknown or mixed objects retain the conservative action/application guard.
    """
    documentary = re.compile(
        r"\b(?:firma|firmante|sello|autenticidad|procedencia|trazabilidad)\b|"
        r"\b(?:cadena de custodia|registro de ingreso)\b|"
        r"\bintegridad\s+(?:del?|de la)\s+(?:archivo|documento|copia|ejemplar)\b"
    )
    other_object = re.compile(
        r"\b(?:derech\w*|obligaci\w*|competenc\w*|competente\w*|facultad\w*|"
        r"autoriz\w*|benefici\w*|ejecucion|tramite|cumplimiento|procedimiento|"
        r"norma|regla|reglamento|estatuto|disposicion|ley|juridic\w*|legal\w*|segun)\b"
    )
    clauses = re.split(r"([.;!?])", text)
    for index, clause in enumerate(clauses):
        parts = re.split(r",|\b(?:y|e)\b", clause)
        if len(parts) > 1 and re.fullmatch(
            r"\s*(?:para|respecto de)\s+(?:cada|todas las|todos los|la|el|las|los)\s+"
            r"(?:copias?|archivos?|documentos?|ejemplares?)\s*", parts[0]
        ):
            parts = parts[1:]
        if not all(documentary.search(part) and not other_object.search(part) for part in parts):
            continue
        # Verify a signature is not an instruction to execute the rule's procedure.
        clause = re.sub(r"\b(?:verificar|verifique[n]?)\b", "informar", clause)
        # Only documentary identity subjects; 'me/le corresponde' still denotes
        # a potential entitlement. No matching across coordinated predicates.
        clause = re.sub(
            r"\b(?:firma|sello|archivo|documento|copia|ejemplar)\b"
            r"(?:(?!\b(?:y|e|me|nos|le|les)\b)[^.;,!?]){0,160}\bcorresponde[n]?\b"
            r"(?=\s+a\s+(?:(?:la|el|esa|ese|esta|este|su|un|una)\s+)?"
            r"(?:persona|suscriptor|firmante|archivo|documento|copia|ejemplar)\b|"
            r"\s+al\s+(?:suscriptor|firmante|archivo|documento|ejemplar)\b)",
            lambda match: re.sub(r"\bcorresponde[n]?\b", "coincide", match.group()), clause,
        )
        clause = re.sub(
            r"\ba (?:quien|que persona) corresponde (?:la|esta|esa) firma\s+"
            r"(?:(?:del?|en (?:el|la))\s+(?:ejemplar|archivo|documento|copia)\b|"
            r"(?:consignada|estampada)\b|que (?:consta|aparece)\b)",
            lambda match: match.group().replace("corresponde", "pertenece"), clause,
        )
        clauses[index] = clause
    return "".join(clauses)


def _copy_without_legal_application(request):
    """A copy's authentication is independent of its rule's legal effect.

    This only waives catalog validity metadata. Material uncertainties always
    remain, including when the reader uses application=unresolved for authenticity.
    An incomplete request context cannot establish absence of a legal question.
    """
    intent = classify_request_intent(request)
    context = request.get("context") or {}
    original = context.get("document_context") or {}
    # Preserve comma-coordinated objects until their purpose is known. Splitting
    # 'verifique la firma, la competencia...' first would hide the second object.
    scoped_text = _application_request_text(_positive_copy_requirements([
        _documentary_copy_scope(_plain(request.get("description") or request.get("title") or ""))
    ]))
    scoped_intent = classify_request_intent({"description": scoped_text})
    if (not intent["document_delivery_requested"]
            or context.get("truncated") or original.get("truncated")
            or original.get("omitted_ranges")
            or (scoped_intent["future_action_requested"]
                and not intent["certification_requested"])):
        return False
    text = _application_request_text(_positive_copy_requirements([
        _documentary_copy_scope(_plain(part)) for part in _copy_scope_texts(request)
    ]))
    # Time alone (the document's year or today's delivery) is not legal effect.
    # Keep broad positive/negative questions about effect, even if mislabeled as
    # attributed content by the reader. Negated decision mandates were removed above.
    return not bool(re.search(
        r"\b(?:vigencia|vigentes?|vigor|aplic\w*|derog\w*|rige[n]?|regia[n]?|rigio|rigieron|"
        r"regir\w*|regul\w*|obligatori\w*|exigib\w*|puedo|podemos|debo|debemos|"
        r"corresponde|derechos?|suspendid[ao]s?|suspension)\b|\bpara\s+mi\s+caso\b|"
        r"\b(?:efectos?|validez|fuerza)\s+(?:juridic\w*|normativ\w*|legal\w*|vinculante)\b|"
        r"\b(?:surt\w*|produc\w*|tiene|conserva|sin)\s+efectos?\b|"
        r"\b(?:sigue|continua)\s+(?:siendo\s+)?valid[ao]\b|"
        r"\b(?:norma|regla|disposicion)\b[^.;]{0,100}\bvalid[ao]\b|"
        r"\bvalidez\b[^.;]{0,100}\b(?:norma|regla|disposicion|resolucion|circular|acuerdo)\b",
        text))


def _normative_description_only(request):
    """An attributed norm can explain its text, not silently establish applicable law."""
    if _requires_more_than_attribution(request):
        return False
    text = _plain(request.get("description") or request.get("title") or "")
    return bool(re.search(
        r"\b(?:segun|contenido|texto|transcrib\w*|describe|describio|describia|"
        r"dice|decia|establece|establecio|establecia|fija|fijo|fijado|"
        r"preve|preveia|senala|senalo|senalaba|indicaba|indica|indico|"
        r"consta|constaba|dispone|disponia|dispuesto|definio|definido)\b", text))


def validated_coverage(selection, request, supports):
    """Solo admite pasajes literales de respaldos que pasaron los filtros de ámbito."""
    requirement_checks = validate_requirement_checks(request, selection)
    coverage = [item.model_dump() for item in selection.coverage]
    index = {s["chunk_id"]: s for s in supports}
    if selection.coverage_complete and (not coverage or not index):
        raise DomainError("La cobertura completa necesita afirmaciones y pasajes seleccionados.")
    source_uses = {}
    source_applications = {}
    for item in coverage:
        if any(not item[key].strip() for key in ("aspect", "claim", "explanation")):
            raise DomainError("Cada afirmación necesita explicar su alcance y respaldo.")
        if not item["citations"]:
            raise DomainError("Una afirmación respaldada necesita al menos un pasaje literal.")
        for citation in item["citations"]:
            source = index.get(citation["chunk_id"])
            quote = _literal(citation["quote"])
            if not source:
                raise DomainError(
                    "La evaluación citó un fragmento que no incluyó "
                    "entre los soportes seleccionados.")
            if not quote or quote not in _literal(source["quote"]):
                raise DomainError(
                    "La cobertura no coincide literalmente con un pasaje seleccionado.")
            if source.get("category") == "historical_petition":
                raise DomainError("Una petición anterior no acredita una respuesta ni sus hechos.")
            role = source["role"]
            use = item["use"]
            if (source.get("category") in {"national_norm", "institutional_norm"}
                    and use in {"verified_fact", "official_status"}):
                raise DomainError(
                    "Una norma no acredita un hecho ni un estado oficial del expediente.")
            if use not in coverage_uses(source, role):
                raise DomainError("El respaldo no permite el uso declarado en la cobertura.")
            source_uses.setdefault(source["source_id"], set()).add(use)
            source_applications.setdefault(source["source_id"], set()).add(
                item["application"]["status"])
    intent = classify_request_intent(request)
    scoped_intent = classify_request_intent({"description": _application_request_text(
        _plain(request.get("description") or request.get("title") or ""))})
    copy_scope = request
    if intent["intents"] == ["document_delivery"]:
        # 'Envíeme hoy una copia' sets a delivery time, not current legal effect.
        # Other signals (vigente, para mi caso, versión oficial...) remain intact.
        copy_scope = {**request, "description": re.sub(
            r"\bhoy\b", "", _plain(request.get("description") or request.get("title") or ""))}
    return {
        "policy_version": POLICY_VERSION,
        "coverage_complete": selection.coverage_complete,
        "coverage": coverage,
        "uncertainties": validated_uncertainties(
            selection, request, coverage, supports, requirement_checks),
        "request_requirements": request.get("request_requirements", []),
        "requirement_checks": requirement_checks,
        # Indices in requirement_checks refer to this original model evaluation,
        # not the later normalized/grouped list of operational checks.
        "evaluated_gaps": [item.model_dump() for item in selection.missing],
        "source_uses": {sid: sorted(uses) for sid, uses in source_uses.items()},
        "source_applications": {sid: sorted(states) for sid, states in source_applications.items()},
        "document_states": document_delivery_states(request, supports),
        "attribution_only_allowed": not _requires_more_than_attribution(request),
        "normative_description_only": _normative_description_only(request),
        "copy_without_current_application": (
            intent["document_delivery_requested"]
            and not (intent["future_action_requested"] or scoped_intent["future_action_requested"])
            and not (intent["certification_requested"] or scoped_intent["certification_requested"])
            and not _requests_current_application(copy_scope)),
        "copy_without_legal_application": _copy_without_legal_application(request),
        "assessment_kind": "model_coverage_with_literal_checks",
    }


def metadata_check_required(source, coverage, reason):
    """No necesita expedición oficial para explicar contenido atribuido y localizado."""
    if reason not in {"provenance", "issued_version", "validity"}:
        return True
    uses = coverage.get("source_uses", {}).get(source["source_id"], [])
    # Una fuente contextual no usada por ninguna afirmación no impone condiciones
    # a las afirmaciones que están cubiertas por otros archivos seleccionados.
    if not uses:
        return not coverage.get("coverage_complete")
    state = coverage.get("document_states", {}).get(source["source_id"], {})
    if (reason in {"provenance", "issued_version"}
            and coverage.get("copy_without_current_application")
            and state.get("availability") == "identified_copy"
            and state.get("authentication_requested") is False
            and set(uses) <= {"attributed_content", "document_delivery"}):
        # Only metadata_only gaps reach this waiver. A concrete defect, missing
        # annex, requested signed version or historical dispatch remains evidence.
        return False
    if (reason == "validity"
            and source.get("category") in {"national_norm", "institutional_norm"}
            and state.get("availability") == "identified_copy"
            and coverage.get("copy_without_legal_application")
            and set(uses) <= {"attributed_content", "document_delivery"}):
        # Authentication can be supported/unresolved without asserting legal
        # application. Its specific uncertainty and provenance checks stay open.
        return False
    if (reason == "validity"
            and set(coverage.get("source_applications", {}).get(source["source_id"], []))
            & {"supported", "unresolved"}):
        return True
    if (reason == "validity" and source.get("category") in {"national_norm", "institutional_norm"}
            and coverage.get("copy_without_current_application")
            and coverage.get("copy_without_legal_application", True)
            and set(uses) <= {"attributed_content", "document_delivery"}):
        return False
    if (reason == "validity" and source.get("category") in {"national_norm", "institutional_norm"}
            and not coverage.get("normative_description_only", False)):
        return True
    return not coverage.get("attribution_only_allowed") or set(uses) != {"attributed_content"}


def classify_proposed_gaps(items, supports, coverage):
    """Separa SOLO avisos explícitamente derivados de metadatos; audita la decisión.

Un problema de identidad, contradicción, extracción o documento solicitado nunca
se descarta porque haya una cobertura afirmativa. La cobertura no anula brechas.
"""
    index = {s["source_id"]: s for s in supports}
    retained, observations = [], []
    for item in items:
        ids = item.get("linked_source_ids", [])
        reason = item.get("reason_code")
        metadata_only = item.get("basis") == "metadata_only"
        if (metadata_only and ids and all(sid in index for sid in ids)
                and all(not metadata_check_required(index[sid], coverage, reason) for sid in ids)):
            observations.append({
                "original": item,
                "decision": "non_blocking_metadata",
                "reason": (
                    "Se solicita la copia identificada, no determinar los efectos jurídicos "
                    "de la norma. La vigencia de catálogo no condiciona esa copia; "
                    "se conservan la autenticidad solicitada y los cotejos concretos."
                    if reason == "validity" and coverage.get("copy_without_legal_application")
                    else
                    "El archivo solicitado está identificado para preparar su copia. "
                    "Este estado de catálogo no impide ofrecer la copia disponible; "
                    "se conservan los cotejos concretos y la entrega pendiente, "
                    "sin acreditar autenticidad, certificación ni envío."
                    if any(coverage.get("document_states", {}).get(sid, {}).get(
                        "availability") == "identified_copy" for sid in ids)
                    else "La respuesta expone contenido atribuido; este metadato de catálogo "
                    "no identifica una afirmación sin respaldo ni acredita "
                    "expedición o autenticidad."
                ),
            })
        else:
            retained.append(item)
    return retained, observations
