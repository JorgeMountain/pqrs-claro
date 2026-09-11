"""Local claim signals with clause scope, not a substitute for semantic review.

These checks reject clear unsupported assertions. They do not treat describing a
question, a search limitation or an explicitly deferred check as an assertion of
the underlying fact. Citation entailment, anaphora and ambiguous attribution still
belong to the model's semantic comparison and the subsequent human review.
"""

from __future__ import annotations

import re
import unicodedata

from .source_assessment import _historical_document_status
from .source_retrieval import HISTORICAL_CATEGORIES


def _plain(text: str) -> str:
    return " ".join(
        "".join(
            char
            for char in unicodedata.normalize("NFD", text.casefold())
            if unicodedata.category(char) != "Mn"
        ).split()
    )


_YEAR = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
_CURRENT = re.compile(r"\b(?:actualmente|a dia de hoy|hoy en dia|en la actualidad)\b")
_SOURCE = (
    r"(?:oficio|antecedente|borrador|correo|anexo|documento|archivo|pasaje|fuente|fragmento)s?"
)
_REPORT = (
    r"(?:indic\w*|senal\w*|inform\w*|registr\w*|refir\w*|refier\w*|consign\w*|"
    r"mencion\w*|declar\w*|afirm\w*|describ\w*|recog\w*|establec\w*|conclu\w*|"
    r"identific\w*|precis\w*)"
)
_ATTRIBUTION = re.compile(
    rf"\b(?:segun|de acuerdo con|conforme a)\b|"
    rf"\b(?:en|como) (?:el|un|otro|ese|este|aquel|los|esos)?\s*"
    rf"(?:mismo\s+)?{_SOURCE}\b|"
    rf"\b(?:respuesta|comunicacion|referencia) (?:institucional )?"
    rf"(?:historica|anterior|previa)\b|"
    rf"\b{_SOURCE}\b.{{0,120}}\b(?:historico|historica|{_REPORT})\b|"
    rf"\b(?:atribu\w*|contenido|conclusion)\b.{{0,70}}\b{_SOURCE}s?\b"
)
_LIMIT = re.compile(
    r"\b(?:no|tampoco) (?:(?:se|le|lo|la)\s+)?"
    r"(?:permite\w*|puede\w*|basta\w*|acredita\w*|demuestra\w*|confirma\w*|"
    r"prueba\w*|establece\w*|significa\w*|implica\w*|constituye\w*|sustituye\w*|"
    r"equivale\w*|afirma\w*|atribuye\w*|presenta\w*)\b|"
    r"\bsin (?:afirmar|acreditar|confirmar|atribuir\w*|presentar|certificar|concluir)\b|"
    r"\bno (?:contiene\w*|incorpora\w*)\b.{0,100}\b(?:declaracion|respuesta|soporte)\b|"
    r"\b(?:debe diferenciarse|debe distinguirse|es distinto de establecer)\b"
)
_INQUIRY = re.compile(
    r"\b(?:la solicitud|la pregunta|la peticion|la consulta|el interrogante)\b.{0,60}"
    r"\b(?:solicita|pregunta|plantea|pide|consulta|versa|se refiere|busca)\b|"
    r"\b(?:se solicita|se pregunta|se pide|solicita confirmar|solicita informar)\b|"
    r"\b(?:tambien|ademas) (?:plantea|solicita|pregunta|pide|consulta)\b|"
    r"\b(?:queda|sigue|permanece|esta|deja)\w* (?:expresamente )?pendiente\b|"
    r"\b(?:requiere|debe|debera)\w* (?:ser )?(?:verific\w*|cotej\w*|confirm\w*)\b"
)
_ASSERTIVE_START = (
    r"(?:actualmente|hoy en dia|en la actualidad|confirmamos|afirmamos|certificamos|"
    r"en (?:el semestre )?(?:19|20)\d{2}|"
    r"se (?:adjunta\w*|entrega\w*|certifica\w*|remiti\w*|niega|deniega)|"
    r"(?:el|la|los|las) (?:\w+\s+){1,4}"
    r"(?:es|son|esta\w*|fue\w*|pertenece\w*|dict\w*|dirigi\w*|aprob\w*))"
)
_BOUNDARY = re.compile(
    rf"(?<=[.!?;])\s+|\s+(?:pero|sin embargo|no obstante|mientras que)\s+|"
    rf",\s*(?={_ASSERTIVE_START}\b)|\s+y\s+(?={_ASSERTIVE_START}\b)"
)
_OPERATION = re.compile(
    r"\b(?:se adjunta(?:n)?|adjuntamos|se entrega(?:n)?|hacemos entrega|se hace entrega|"
    r"por (?:medio de )?la presente se certifica|certificamos|se certifica que|"
    r"queda certificado|se niega (?:la|el)|se deniega|se remitio|hemos remitido)\b"
)
_ISSUED = re.compile(
    r"\b(?:(?:ya )?(?:fue|esta|ha sido|quedo) (?:oficialmente )?"
    r"(?:expedido|expedida|emitido|emitida|notificado|notificada)|"
    r"respuesta oficial expedida|documento oficial expedido|"
    r"oficio expedido|respuesta expedida|se expidio)\b"
)
_DRAFT_LIMIT = re.compile(
    r"\b(?:borrador|documento de trabajo|version de trabajo|version no definitiva|"
    r"pendiente de expedicion|no expedid[oa]|sin expedir)\b|"
    r"\b(?:no|sin)\b.{0,100}\b(?:respuesta|documento|oficio)\b.{0,50}"
    r"\b(?:oficial|expedid[oa])\b|\bno (?:se ha|ha sido|fue|esta) expedid[oa]\b"
)


def _clauses(text: str) -> list[str]:
    # Coordinated positive assertions get their own scope. A negation in the
    # preceding clause must never exempt a second assertion from these checks.
    return [part.strip(" ,") for part in _BOUNDARY.split(_plain(text)) if part.strip(" ,")]


def _nonassertive(clause: str, end: int | None = None) -> bool:
    prefix = clause if end is None else clause[:end]
    if "¿" in prefix or _LIMIT.search(prefix) or _INQUIRY.search(prefix):
        return True
    if end is None:
        return False
    # "Actualmente no puede confirmarse..." puts the time marker before the
    # limiting predicate. Only an immediate predicate gets this exemption.
    after = clause[end:]
    if _CURRENT.match(after) and re.match(
        rf"^{_CURRENT.pattern}\s+(?:no|tampoco)\s+",
        after,
    ):
        return bool(_LIMIT.search(after))
    # A time period can precede a deferred *application*, rather than an event:
    # "Su vigencia y aplicación a 2025 deben cotejarse". Do not exempt an
    # earlier positive conclusion about the same application.
    return bool(
        re.match(
            r"^(?:su|la|esa|esta) (?:vigencia|aplicacion|comprobacion|verificacion|alcance)\b",
            clause,
        )
        and _INQUIRY.search(clause)
        and not re.search(r"\b(?:fue|era|ha sido|quedo|se confirmo|se aprobo)\b", clause)
    )


def _search_description(clause: str, current: re.Match) -> bool:
    return bool(
        re.search(r"\b(?:soportes|fuentes|fragmentos|candidatos)\b", clause[: current.start()])
        and re.match(r"\s+(?:seleccionad|citad|recuperad|disponible)\w*", clause[current.end() :])
    )


def _historical_remission(clause: str, previous: str, text: str) -> bool:
    """Allow bounded reporting of a historical remittance, never our own action.

    A comma can separate "Según el oficio" from "se remitió" during scope
    splitting. Inherit only that immediately adjacent attribution, never one
    from a completed sentence. The semantic checker still verifies its citation.
    """
    attributed = _ATTRIBUTION.search(clause) or (
        previous
        and previous[-1] not in ".!?;"
        and re.match(r"^(?:segun|de acuerdo con|conforme a)\b", previous)
    )
    limited = any(
        _LIMIT.search(part)
        and re.search(r"\b(?:envio|entrega|remision|actual|actualmente)\b", part)
        for part in _clauses(text)
    )
    return bool(attributed and limited)


_REQUEST_SCOPE_META = re.compile(
    r"^este alcance delimita lo solicitado y no acredita por si mismo "
    r"ninguno de los hechos consultados[.]?$"
)
_REQUEST_SCOPE_HISTORY = re.compile(
    rf"\b(?:segun|de acuerdo con|conforme a)\b|"
    rf"\b(?:en|como) (?:el|un|ese|este|los|esos) (?:mismo )?{_SOURCE}\b|"
    r"\b(?:respuesta|comunicacion|referencia) (?:institucional )?"
    r"(?:historica|anterior|previa)\b|"
    rf"\b{_SOURCE}\b.{{0,120}}\b"
    r"(?:indica|indico|senala|senalo|informa|informo|registra|registro|"
    r"declara|declaro|afirma|afirmo|describe|describio|concluye|concluyo|"
    r"precisa|preciso|consigna|consigno|recoge|recogio|acredita|demuestra|confirma|prueba)\b"
)
_REQUEST_SCOPE_ESCAPE = re.compile(
    r"\b(?:porque|ya que|dado que|puesto que|por tanto|por lo tanto|en consecuencia)\b|"
    r"\b(?:lo|hecho) que (?:acredita|demuestra|confirma|prueba|establece)\b|"
    r"\b(?:solicitud|pregunta|peticion|consulta) (?:anterior|previa|historica)\b|"
    r"\b(?:y|e) (?:(?:ya|tambien|ademas) )?"
    r"(?:fue|fueron|es|son|quedo|quedaron|confirmamos|afirmamos|certificamos|"
    r"(?:se|hemos|ha|han) (?:\w+\s+){0,2}"
    r"(?:confirm\w*|acredit\w*|aprob\w*|remit\w*|adjunt\w*|entreg\w*))\b"
)


def is_request_scope_only(text: str, request: dict | None) -> bool:
    """Allow removal only of a clearly metatextual current-request summary.

    This deliberately recognizes a small set of forms. Every independent clause
    must describe what is requested, with one narrow scope-only closing sentence
    allowed. A historical report, a substantive limit or an ambiguous clause
    makes the whole paragraph ineligible. The semantic checker must separately
    identify it as redundant for this request; this function cannot establish
    semantic equivalence between a paraphrase and the petition.
    """
    if not isinstance(request, dict) or not any(
        str(request.get(key) or "").strip() for key in ("description", "text", "title")
    ):
        return False
    normalized = _plain(text)
    if not normalized or any(mark in normalized for mark in ('"', "«", "»", "“", "”")):
        return False
    if _REQUEST_SCOPE_ESCAPE.search(normalized):
        return False

    request_id = _plain(str(request.get("id") or ""))
    optional_id = rf"(?: {re.escape(request_id)})?" if request_id else ""
    scope_start = re.compile(
        r"^(?:como alcance de (?:la|esta) solicitud,\s*)?"
        r"(?:(?:tambien|ademas),?\s+)?"
        r"(?:se (?:pide|solicita|pregunta)|"
        rf"la (?:(?:actual|presente) )?(?:solicitud|pregunta|peticion|consulta){optional_id} "
        r"(?:pide|solicita|pregunta|consulta|plantea|busca|versa sobre|se refiere a))\b"
    )
    saw_request = False
    for clause in _clauses(normalized):
        if saw_request and _REQUEST_SCOPE_META.fullmatch(clause):
            continue
        if _REQUEST_SCOPE_HISTORY.search(clause):
            return False
        start = scope_start.match(clause)
        if not start and saw_request:
            start = re.match(
                r"^(?:tambien|ademas),? (?:pide|solicita|pregunta|consulta|plantea)\b", clause
            )
        if not start or not clause[start.end() :].strip(" ,.:;?!"):
            return False
        # These cues remain ineligible even inside a possible indirect question:
        # a false negative keeps the paragraph for review instead of deleting it.
        if _LIMIT.search(clause) or _OPERATION.search(clause) or re.search(
            r"\bno existe(?:n)?\b", clause
        ):
            return False
        saw_request = True
    return saw_request


def paragraph_claim_checks(
    text: str,
    sources: list[dict],
    *,
    paragraph_index: int = 0,
    request: dict | None = None,
) -> tuple[list[dict], list[dict]]:
    """Return legacy-compatible local checks/issues for one cited paragraph.

    ``request`` is accepted for the caller's context but never makes its years
    evidence. Only explicit question/limitation wording exempts a year check.
    A passed signal means no clear local violation, not semantic entailment.
    """
    checks: list[dict] = []
    issues: list[dict] = []

    def check(code: str, passed: bool, description: str) -> None:
        checks.append({"code": code, "passed": passed, "description": description})
        if not passed:
            issues.append(
                {
                    "code": code,
                    "description": description,
                    "paragraph_index": paragraph_index,
                }
            )

    clauses = _clauses(text)
    historical = [source for source in sources if source.get("category") in HISTORICAL_CATEGORIES]
    attributed = bool(_ATTRIBUTION.search(_plain(text)))
    factual_clauses = [clause for clause in clauses if not _nonassertive(clause)]
    check(
        "historical_attribution",
        not historical or attributed or not factual_clauses,
        "Atribuir el contenido histórico a su fuente; preguntas y límites no afirman ese hecho.",
    )
    source_text = " ".join(
        f"{source.get('title', '')} {source.get('filename', '')} {source.get('quote', '')}"
        for source in sources
    )
    source_years = set(_YEAR.findall(source_text))
    request_years = set(_YEAR.findall(str((request or {}).get("description", ""))))
    unsupported_years = []
    for clause in clauses:
        for year in _YEAR.finditer(clause):
            # Date in an explicitly delimited object of the question, followed
            # by a limitation. Request dates never ground a positive assertion.
            question_object = (
                year.group() in request_years
                and re.match(r"^(?:sobre|respecto de|en cuanto a)\b", clause)
                and "," not in clause[: year.start()]
                and bool(_LIMIT.search(clause[year.end() :]))
            )
            if year.group() not in source_years and not (
                _nonassertive(clause, year.start()) or question_object
            ):
                unsupported_years.append(year.group())
    check(
        "period_grounded",
        not unsupported_years,
        "Los años afirmados como hechos deben estar respaldados por sus fuentes citadas.",
    )
    current_assertions = [
        current
        for clause in clauses
        for current in _CURRENT.finditer(clause)
        if not _nonassertive(clause, current.start()) and not _search_description(clause, current)
    ]
    check(
        "historical_current_fact",
        not historical or not current_assertions or any(s.get("role") == "fact" for s in sources),
        "Un antecedente histórico no acredita por sí solo una afirmación positiva de actualidad.",
    )
    has_draft = any(_historical_document_status(source) == "draft" for source in historical)
    issued_assertions = [
        issued
        for clause in clauses
        for issued in _ISSUED.finditer(clause)
        if not _nonassertive(clause, issued.start())
        and not re.search(
            r"\bno\s+(?:se\s+|como\s+(?:(?:un|una|el|la)\s+)?)?$",
            clause[: issued.start()],
        )
    ]
    check(
        "draft_status_preserved",
        not has_draft
        or (
            (bool(_DRAFT_LIMIT.search(_plain(text))) or not factual_clauses)
            and not issued_assertions
        ),
        "Conservar que el archivo es de trabajo o no expedido, sin atribuirle expedición oficial.",
    )
    operational = []
    for number, clause in enumerate(clauses):
        for operation in _OPERATION.finditer(clause):
            historical_remission = (
                operation.group() == "se remitio"
                and historical
                and _historical_remission(clause, clauses[number - 1] if number else "", text)
            )
            if not (
                _nonassertive(clause, operation.start())
                or re.search(r"\b(?:no|tampoco)\s+$", clause[: operation.start()])
                or historical_remission
            ):
                operational.append(operation)
    check(
        "no_operational_claim",
        not operational,
        "El borrador no acredita adjuntos, entrega, certificación ni denegación definitiva.",
    )
    nonexistence = [
        match
        for clause in clauses
        for match in re.finditer(r"\bno existe(?:n)?\b", clause)
        if not _nonassertive(clause, match.start()) and not _ATTRIBUTION.search(clause)
    ]
    check(
        "no_nonexistence_inference",
        not nonexistence,
        "No convertir la ausencia de resultados en una declaración de inexistencia.",
    )
    if historical and all(s.get("category") == "historical_petition" for s in historical):
        check(
            "petition_is_allegation",
            bool(re.search(r"\b(?:solicit|peticionari|aleg|manifiest|pregunt)", _plain(text))),
            "Una petición anterior solo sustenta lo solicitado o alegado por su autor.",
        )
    return checks, issues
