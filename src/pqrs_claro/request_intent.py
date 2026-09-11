"""Actos pedidos por una pregunta, separados de hechos o documentos mencionados.

La clasificación orienta los pendientes; no decide competencias ni acredita que una
actuación se haya realizado. El contexto recuperado sirve para interpretar el objeto,
pero las actuaciones de padres y hermanos no se convierten en exigencias nuevas.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any


def _plain(value: str) -> str:
    return "".join(
        char for char in unicodedata.normalize("NFKD", value.casefold())
        if not unicodedata.combining(char)
    )


_INFORMATION = re.compile(
    r"\b(?:informar|informe[n]?|aclarar|aclare[n]?|precisar|precise[n]?|"
    r"confirmar|confirme[n]?|responder|responda[n]?|explicar|explique[n]?|"
    r"indicar|indique[n]?|saber|conocer)\b"
)
_DELIVERY = re.compile(
    r"\b(?:copias?|anexar|anexe[n]?|adjuntar|adjunte[n]?|remitir|remita[n]?|"
    r"entregar|entregue[n]?|enviar|envie[n]?|facilitar|facilite[n]?|acceso a)\b"
)
_FUTURE = re.compile(
    r"\b(?:certificar|certifique[n]?|expedir|expida[n]?|emitir|emita[n]?|"
    r"firmar|firme[n]?|verificar|verifique[n]?|vigilar|vigile[n]?|"
    r"controlar|controle[n]?|supervigilancia|juramento|adelante[n]?|ejerza[n]?)\b"
)
_CERTIFICATE = r"certifica(?:cion(?:es)?|dos?|das?)"


def _request_clauses(text: str) -> list[str]:
    # Una oración puede contener varios actos coordinados. La parte subordinada a
    # «informar si / quién» describe la pregunta y no manda ejecutar esos verbos.
    clauses = re.split(
        r"[.!?]\s+|\n+|;\s*(?=(?:solicita|pide|solicito|pido)\b)|"
        r"\b(?:tambien|ademas)\s+(?=(?:solicita|pide|solicito|pido)\b)", text
    )
    return [clause.strip() for clause in clauses if clause.strip()]


def _is_information_clause(clause: str) -> bool:
    if re.match(r"^[¿\s]*(?:quien|quienes|cuando|como|por que|puede|podia|existe)\b", clause):
        return True
    information = _INFORMATION.search(clause)
    if not information:
        return False
    other = [match for pattern in (_DELIVERY, _FUTURE) if (match := pattern.search(clause))]
    return not other or information.start() < min(match.start() for match in other)


def _certification_requested(text: str) -> bool:
    for clause in _request_clauses(text):
        # «Solicito aclarar quién expidió la certificación» o «si podía firmar
        # certificados» son información. Una segunda orden coordinada se conserva.
        if _is_information_clause(clause):
            command = re.search(
                r"\b(?:y|ademas)\s+(?:que\s+)?(?:se\s+)?"
                r"(?:certifique[n]?|certificar|expida[n]?|expedir|emita[n]?|emitir)\b",
                clause,
            )
            if not command:
                continue
            clause = clause[command.start():]
        if re.search(r"\b(?:certificar|certifique[n]?)\b", clause):
            if re.search(
                r"\b(?:documentos|archivos|actas|registros|pruebas|soportes)\b"
                r"[^.;]{0,180}\bque\s+certifique[n]?\b", clause
            ) and not re.search(r"\b(?:expida[n]?|expedir|emita[n]?|emitir)\b", clause):
                continue
            return True
        if re.search(
            rf"\b(?:expedir|expida[n]?|emitir|emita[n]?)\b[^.;]{{0,180}}\b{_CERTIFICATE}\b",
            clause,
        ):
            return True
        # Pedir copia de un certificado existente no equivale a pedir expedirlo.
        if _DELIVERY.search(clause):
            continue
        if re.search(
            rf"\b(?:solicito|solicita|pido|pide|obtener)\s+"
            rf"(?:(?:una?|la|el|nueva?|nuevo)\s+){{0,3}}{_CERTIFICATE}\b",
            clause,
        ):
            return True
    return False


def classify_request_intent(request: dict[str, Any]) -> dict[str, Any]:
    """Clasifica el mandato propio de la pregunta sin heredar actos de sus hermanos."""
    text = _plain(str(request.get("description") or request.get("title") or ""))
    intents: set[str] = set()
    certification = _certification_requested(text)
    for clause in _request_clauses(text):
        information_first = _is_information_clause(clause)
        if information_first:
            intents.add("information")
            # Un verbo dentro del contenido interrogado no es una orden nueva.
            # Sí lo es «... y que adjunte una copia / y expida una certificación».
            coordinated = re.search(
                r"\b(?:y|ademas)\s+(?:que\s+)?(?:se\s+)?"
                r"(?:anexe[n]?|adjunte[n]?|remita[n]?|entregue[n]?|envie[n]?|"
                r"expida[n]?|emita[n]?|certifique[n]?|firme[n]?|verifique[n]?)\b",
                clause,
            )
            if not coordinated:
                continue
            clause = clause[coordinated.start():]
        # Una condición «no se entreguen documentos sin ...» no es una entrega
        # adicional; conserva la vigilancia pedida en su cláusula principal.
        directive = re.sub(
            r"\bno\s+(?:se\s+)?(?:entregue[n]?|adjunte[n]?|envie[n]?|remita[n]?)\b",
            "condicion", clause,
        )
        delivery, future = _DELIVERY.search(directive), _FUTURE.search(directive)
        # Supervisar que otro responda o entregue es una actuación futura. No
        # multiplica las mismas obligaciones documentales en cada supervisor.
        if future and (not delivery or future.start() < delivery.start()):
            intents.add("future_action")
            if re.search(r"\by\s+(?:que\s+)?(?:aclare[n]?|informe[n]?|confirme[n]?)\b", clause):
                intents.add("information")
            continue
        if delivery:
            intents.add("document_delivery")
            if re.search(r"\b(?:y|que)\s+(?:explique[n]?|aclare[n]?|informe[n]?)\b", clause):
                intents.add("information")
        elif _INFORMATION.search(clause):
            intents.add("information")
    if certification:
        intents.add("future_action")
    if not intents:
        intents.add("information")
    ordered = [
        value for value in ("information", "document_delivery", "future_action") if value in intents
    ]
    return {
        "primary": ordered[0] if len(ordered) == 1 else "mixed",
        "intents": ordered,
        "certification_requested": certification,
        "document_delivery_requested": "document_delivery" in intents,
        "future_action_requested": "future_action" in intents,
    }


def fulfillment_actions(request: dict[str, Any]) -> list[dict[str, Any]]:
    """Obligaciones futuras visibles; no se dan por cumplidas ni impiden redactar.

La aprobación es del contenido que se va a generar. Una firma o entrega posterior
no puede exigirse como prueba de ese mismo contenido antes de prepararlo.
"""
    intent = classify_request_intent(request)
    text = _plain(str(request.get("description") or request.get("title") or ""))
    actions = []
    if intent["certification_requested"]:
        actions.append({
            "kind": "clarification",
            "reason_code": "certification_preparation",
            "description": (
                "Preparar la certificación solicitada y someter su contenido a la autoridad "
                "competente para su expedición. Conservar los hechos y soportes específicos; "
                "el borrador no acredita que la certificación ya haya sido expedida."
            ),
        })
    elif intent["future_action_requested"]:
        if re.search(r"\b(?:firme[n]?|firmar)\b", text):
            reason, description = "response_signature", (
                "Tramitar la firma de la respuesta aprobada por el responsable solicitado. "
                "La firma futura no es evidencia exigible para preparar esta misma respuesta."
            )
        elif re.search(
            r"supervigilancia|vigilancia|\b(?:verifique[n]?|verificar|vigile[n]?)\b", text
        ):
            reason, description = "supervision", (
                "Asignar y tramitar la actuación de vigilancia o verificación solicitada "
                "ante el responsable competente, conservando las preguntas a las que se refiere. "
                "Su ejecución se registra cuando ocurra; "
                "no presupone una respuesta final existente."
            )
        else:
            reason, description = "response_preparation", (
                "Preparar y tramitar la actuación solicitada después de revisar su contenido "
                "y competencia. No dar por realizada su declaración, firma o envío."
            )
        actions.append({"kind": "clarification", "reason_code": reason,
                        "description": description})
    if intent["document_delivery_requested"]:
        actions.append({
            "kind": "clarification",
            "reason_code": "document_delivery",
            "description": (
                "Preparar la entrega de los archivos que correspondan a esta pregunta y "
                "comprobar su inclusión al generar la comunicación. Mantener aparte cualquier "
                "búsqueda o cotejo pendiente; localizar un archivo no acredita su entrega."
            ),
        })
    return [{**item, "stage": "fulfillment", "blocks_approval": False} for item in actions]
