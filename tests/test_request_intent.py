"""Intención: una pregunta sobre certificados no ordena expedirlos."""

import pytest

from pqrs_claro.request_intent import classify_request_intent
from pqrs_claro.source_documents import requested_certification, requested_document


@pytest.mark.parametrize("text", [
    "Solicito aclarar quién expidió la certificación de notas.",
    "Solicita informar si el profesor podía firmar actas, certificados o documentos de notas.",
    "Solicita confirmar si existe un certificado de autenticidad.",
    "¿Quién puede certificar las notas?",
    "Solicita copia de los certificados expedidos en 2015.",
    "Solicita que se vigile que no se entreguen documentos sin certificado de autenticidad.",
    "Solicita acceso a los documentos públicos y archivos institucionales "
    "que certifiquen la titularidad.",
])
def test_certificate_mentions_never_imply_issuance(text):
    assert not requested_certification({"description": text})


@pytest.mark.parametrize("text", [
    "Certifique que el profesor estuvo vinculado en 2015.",
    "Solicita al Secretario General que expida certificados de autenticidad.",
    "Solicito una certificación de la vinculación docente.",
    "Solicito informar los resultados y que expida una certificación de notas.",
])
def test_explicit_new_certification_is_future_action(text):
    result = classify_request_intent({"description": text})
    assert result["certification_requested"]
    assert "future_action" in result["intents"]


@pytest.mark.parametrize("text,intents", [
    ("Solicita informar si el profesor podía firmar certificados.", ["information"]),
    ("Solicita confirmar si los correos fueron enviados en 2015.", ["information"]),
    ("Solicito copia del acta 123 de 2015.", ["document_delivery"]),
    ("Solicita que anexe los planes de trabajo y explique cualquier diferencia.",
     ["information", "document_delivery"]),
    ("Solicita al Decano que verifique que el profesor responda personalmente.",
     ["future_action"]),
    ("Solicita al profesor que firme la respuesta a esta petición.", ["future_action"]),
    ("Solicita al Procurador que adelante supervigilancia "
     "para asegurar que respondan y entreguen documentos.",
     ["future_action"]),
])
def test_separates_information_documents_and_execution(text, intents):
    result = classify_request_intent({"description": text})
    assert result["intents"] == intents
    assert result["primary"] == ("mixed" if len(intents) > 1 else intents[0])


def test_information_child_does_not_inherit_certification_from_context():
    request = {
        "description": "Solicita informar si podía firmar certificados.",
        "title": "Certificados del profesor",
        "context": {"ancestors": [{"description": "Solicita que expida certificados."}]},
    }
    assert classify_request_intent(request)["primary"] == "information"
    assert not requested_certification(request)


@pytest.mark.parametrize("text", [
    "Solicita que responda las preguntas sobre su titularidad; "
    "su facultad para firmar certificados; y los correos de 2013.",
    "Solicita informar si se utilizó la cuenta docente@udea.edu.co "
    "para enviar al correo onman.udea@gmail.com mensajes de la materia.",
])
def test_enumerations_and_email_dots_do_not_create_new_commands(text):
    result = classify_request_intent({"description": text})
    assert result["intents"] == ["information"]
    assert not result["certification_requested"]


def test_question_about_sending_email_is_not_a_request_to_deliver_it():
    assert requested_document({
        "description": "Solicita informar si se utilizó la cuenta docente@udea.edu.co "
        "para enviar correos al peticionario en 2015."
    }) is None
    assert requested_document({"description": "Solicita copia de los correos de 2015."}) == "correo"
