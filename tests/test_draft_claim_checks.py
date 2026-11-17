from copy import deepcopy

import pytest

from pqrs_claro.draft_claim_checks import is_request_scope_only, paragraph_claim_checks

HISTORY = {
    "category": "historical_response",
    "role": "antecedent",
    "document_status": "issued",
    "title": "Respuesta sobre el taller",
    "filename": "respuesta.pdf",
    "quote": "En 2022 se revisó el plan del taller y se identificó a la docente asignada.",
}


def codes(text, sources=None, **kwargs):
    return {
        issue["code"]
        for issue in paragraph_claim_checks(
            text,
            sources if sources is not None else [HISTORY],
            **kwargs,
        )[1]
    }


@pytest.mark.parametrize("text", [
    "Si no existe el depósito, se debe consultar la alternativa prevista.",
    "Cuando no existe una sede local, el documento prevé atención remota.",
    "En caso de que no exista la oficina, debe consultarse la unidad central.",
])
def test_conditional_absence_is_not_an_assertion_of_nonexistence(text):
    assert "no_nonexistence_inference" not in codes(text)


@pytest.mark.parametrize("text", [
    "Si no existe el depósito, se debe consultar. No existe la constancia.",
    "Si el trámite está abierto, no existe el archivo solicitado.",
    "No existe el depósito solicitado.",
])
def test_condition_in_another_clause_cannot_hide_asserted_nonexistence(text):
    assert "no_nonexistence_inference" in codes(text)


@pytest.mark.parametrize("text", [
    "El reglamento indica que, si los anexos se entregan después del plazo, "
    "corresponde al interesado solicitar una excepción.",
    "Cuando se adjuntan planos, el procedimiento exige su escala.",
])
def test_conditional_procedure_does_not_claim_our_delivery(text):
    assert "no_operational_claim" not in codes(text)


@pytest.mark.parametrize("text", [
    "Si procede, se entregan los archivos solicitados.",
    "Cuando se adjuntan planos se revisa su escala. Adjuntamos los archivos.",
    "Si se entregan copias, se certifica que son auténticas.",
])
def test_following_actual_delivery_is_not_exempted_by_condition(text):
    assert "no_operational_claim" in codes(text)


@pytest.mark.parametrize(
    "text",
    [
        "Otra respuesta histórica declaró que se revisó el plan del taller en 2022.",
        "Como antecedente histórico, se informó de la revisión del plan del taller en 2022.",
        "En otro apartado del mismo antecedente se describió el plan del taller de 2022.",
        "En un anexo histórico se identifica una firma atribuida a la docente.",
        "El contenido de esos antecedentes conserva el alcance de la revisión de 2022.",
        "Una respuesta institucional anterior afirmó que la docente figuraba en el plan de 2022.",
        "La conclusión atribuida al archivo corresponde al taller de 2022.",
        "Según el oficio, la docente figuraba en el plan del taller de 2022.",
        "El Oficio 0123-2022 recoge que la docente figuraba en el plan del taller de 2022.",
        "El Oficio 0123-2022 recogió la asignación docente del taller de 2022.",
    ],
)
def test_clear_historical_attribution_variants(text):
    assert "historical_attribution" not in codes(text)


def test_positive_historical_fact_requires_attribution():
    assert "historical_attribution" in codes("El comité aprobó el plan del taller en 2022.")


@pytest.mark.parametrize("text", [
    "La circular, fechada en 2022, consignó que el taller estaba en preparación.",
    "El calendario editorial del archivo municipal prevé publicar el informe en 2022.",
    "El comunicado anunció la fecha prevista para el taller en 2022.",
    "Las circulares anuncian la programación prevista para el taller.",
    "Los calendarios preveían publicar los informes al finalizar el taller.",
    "El calendario previó la publicación del informe en 2022.",
])
def test_documentary_reports_and_forecasts_are_explicit_attributions(text):
    assert "historical_attribution" not in codes(text)


@pytest.mark.parametrize("text", [
    "La circular está archivada. El comité aprobó el plan del taller en 2022.",
    "El calendario editorial está disponible. El taller fue aprobado en 2022.",
    "El comunicado tiene una página. La decisión del comité es definitiva.",
    "El comité prevé publicar su decisión en 2022.",
    "El calendario previo está archivado. El comité aprobó la jornada.",
    "El calendario contiene un anuncio. El comité aprobó la jornada.",
    "El comunicado contiene un nuevo anuncio del taller. El comité aprobó la jornada.",
])
def test_document_mention_or_actor_forecast_alone_is_not_attribution(text):
    assert "historical_attribution" in codes(text)


def test_documentary_forecast_does_not_hide_an_actual_delivery_claim():
    assert "no_operational_claim" in codes(
        "El comunicado anuncia la publicación prevista. Se adjunta el informe solicitado."
    )


@pytest.mark.parametrize("text", [
    "El aviso prevé publicar el resultado el jueves en el tablero.",
    "El acta de recepción consigna que la revisión concluyó el lunes.",
    "El informe describe el estado de la revisión.",
    "Las resoluciones señalan los requisitos de la solicitud.",
    "Los manuales indican cómo presentar la solicitud.",
])
def test_shared_document_classes_allow_brief_documentary_attribution(text):
    assert "historical_attribution" not in codes(text)


@pytest.mark.parametrize("text", [
    "El aviso está archivado. El equipo informó que la jornada concluyó.",
    "El acta tiene dos páginas. El comité declaró aprobado el resultado.",
    "El informe está disponible. La oficina señaló que terminó la revisión.",
    "El equipo informó que la revisión concluyó el lunes.",
])
def test_brief_document_mention_does_not_attribute_another_actors_report(text):
    assert "historical_attribution" in codes(text)


@pytest.mark.parametrize("title,text", [
    ("Boletín técnico 418 de 2022 - Estación de pruebas",
     "El Boletín técnico 418 indica que la revisión sigue en curso."),
    ("Registro de ensayo 927 de 2022",
     "El Registro de ensayo 927 de 2022 consignó que el ensayo concluyó el lunes."),
    ("Balance de laboratorio 62-A - Equipo de medición",
     "El Balance de laboratorio 62-A anunció una nueva revisión."),
])
def test_exact_brief_title_of_cited_source_can_attribute_its_own_report(title, text):
    assert "historical_attribution" not in codes(text, [{**HISTORY, "title": title}])


@pytest.mark.parametrize("text", [
    "El Boletín técnico 418 está archivado. El comité aprobó la jornada.",
    "El Boletín técnico 419 indica que la revisión sigue en curso.",
    "El Boletín técnico 4180 indica que la revisión sigue en curso.",
    "El Boletín técnico 418-A indica que la revisión sigue en curso.",
    "El Boletín técnico 418. El comité informó que aprobó la jornada.",
    "El Boletín técnico 418, el comité informó que aprobó la jornada.",
    "El Boletín clínico 418 indica que la revisión sigue en curso.",
    "El Boletín técnico 418 de 2023 indica que la revisión sigue en curso.",
    "El Boletín técnico 418 informativo está archivado. El comité aprobó la jornada.",
    "El Boletín técnico 418, registro del taller, está archivado. El comité aprobó la jornada.",
])
def test_cited_title_fallback_rejects_other_identity_or_another_actors_predicate(text):
    assert "historical_attribution" in codes(text, [{
        **HISTORY, "title": "Boletín técnico 418 de 2022 - Estación de pruebas",
    }])


@pytest.mark.parametrize("change", ["uncited", "superseded", "old_version", "unreadable"])
def test_cited_title_fallback_requires_the_current_readable_cited_source(change):
    source = {**HISTORY, "title": "Bitácora de ensayo 927 de 2022"}
    if change == "uncited":
        source["title"] = "Bitácora de ensayo 928 de 2022"
    elif change == "superseded":
        source["validity"] = "superseded"
    elif change == "old_version":
        source["is_latest"] = False
    else:
        source["extraction_status"] = "pending"
    assert "historical_attribution" in codes(
        "La Bitácora de ensayo 927 informa que el ensayo concluyó.", [source],
    )


@pytest.mark.parametrize(
    "text",
    [
        "La solicitud pregunta si la docente dirigió el taller en 2025.",
        "Se solicita confirmar la asignación del taller durante 2025.",
        "¿La docente dirigió el taller en 2025?",
        "Según el oficio, la asignación de 2022 no puede trasladarse al semestre 2025.",
        "El antecedente no permite confirmar la asignación del taller en 2025.",
        "Queda pendiente verificar la aplicación de esa regla al período 2025.",
        "Las fuentes no constituyen, por sí solas, una confirmación de la asignación en 2025.",
    ],
)
def test_years_in_questions_and_explicit_limits_are_not_fact_assertions(text):
    assert "period_grounded" not in codes(text)


@pytest.mark.parametrize(
    "text",
    [
        "Según el oficio, la docente dirigió el taller en 2025.",
        "La docente no dirigió el taller en 2025.",
        "La solicitud pregunta por 2025, pero la docente dirigió el taller en 2025.",
        "No se puede confirmar la asignación de 2025. La docente dirigió el taller en 2025.",
        "No se puede confirmar la asignación de 2025 y en 2025 la docente dirigió el taller.",
        "Se solicita confirmar la asignación en 2025 y afirmamos que "
        "la docente dirigió el taller en 2025.",
    ],
)
def test_missing_year_cannot_be_laundered_by_another_question_or_negation(text):
    assert "period_grounded" in codes(text, request={"description": "Pregunta sobre 2025"})


@pytest.mark.parametrize("text", [
    "Aunque se consulta por el ciclo 2031, el texto no identifica ese ciclo como el de 2031.",
    "El documento no precisa que ese periodo corresponda a 2032.",
    "Se consulta sobre 2033; debe cotejarse la aplicación de la regla.",
])
def test_question_and_documentary_period_limit_do_not_date_an_event(text):
    assert "period_grounded" not in codes(text)


@pytest.mark.parametrize("text", [
    "Se consulta por 2031, el documento identifica ese ciclo como el de 2031.",
    "El texto no precisa el ciclo 2032, pero el comité aprobó la solicitud en 2032.",
    "El comité no identificó la solicitud en 2033.",
])
def test_documentary_period_limit_does_not_exempt_a_separate_assertion(text):
    assert "period_grounded" in codes(text)


@pytest.mark.parametrize(
    "text",
    [
        "El antecedente no constituye una confirmación de que la cuenta "
        "pertenezca actualmente a la docente.",
        "Las fuentes no permiten establecer actualmente la pertenencia de la cuenta.",
        "Los soportes actualmente seleccionados no contienen una confirmación de la cuenta.",
        "Los fragmentos actualmente citados describen un trámite histórico.",
        "La solicitud pregunta si la docente dirige actualmente el taller.",
    ],
)
def test_current_markers_in_limits_or_internal_search_are_not_current_facts(text):
    assert "historical_current_fact" not in codes(text)


@pytest.mark.parametrize(
    "text",
    [
        "Según el oficio, actualmente la docente dirige el taller.",
        "No se puede confirmar la titularidad. Actualmente la docente dirige el taller.",
        "No se puede confirmar la titularidad, pero actualmente la docente dirige el taller.",
        "No se puede confirmar la titularidad y actualmente la docente dirige el taller.",
        "Los soportes actualmente seleccionados describen el plan. "
        "Actualmente la docente dirige el taller.",
        "La solicitud pregunta por el taller, pero la docente actualmente dirige el taller.",
    ],
)
def test_positive_current_claims_still_fail(text):
    assert "historical_current_fact" in codes(text)


def test_current_fact_source_keeps_its_existing_role():
    current = {**HISTORY, "category": "case_evidence", "role": "fact"}
    assert "historical_current_fact" not in codes(
        "Según la comprobación del caso, actualmente la docente dirige el taller.",
        [current],
    )


@pytest.mark.parametrize(
    "text",
    [
        "Según el documento de trabajo, se revisó el plan del taller.",
        "El antecedente se conserva como versión no definitiva del documento.",
        "El archivo no ha sido expedido y se conserva únicamente como antecedente.",
        "Según el archivo, se describió el taller, sin atribuirle una respuesta oficial expedida.",
        "El documento queda pendiente de expedición; registra un análisis anterior.",
    ],
)
def test_clear_draft_status_without_required_keyword(text):
    assert "draft_status_preserved" not in codes(text, [{**HISTORY, "document_status": "draft"}])


@pytest.mark.parametrize(
    "text",
    [
        "Según el archivo, se revisó el plan del taller.",
        "El borrador fue expedido oficialmente.",
        "El archivo no ha sido expedido, pero el documento fue expedido oficialmente.",
        "El documento es un borrador. Esta respuesta oficial expedida certifica la asignación.",
    ],
)
def test_draft_cannot_be_promoted_by_a_caution_elsewhere(text):
    assert "draft_status_preserved" in codes(text, [{**HISTORY, "document_status": "draft"}])


@pytest.mark.parametrize(
    "text",
    [
        "No se afirma que se adjunta el acta.",
        "El antecedente no acredita que se entrega el acta en este trámite.",
        "La solicitud pregunta si se remitió el acta.",
        "No se adjunta el acta en este borrador interno.",
        "La ausencia de resultados no equivale a afirmar que no existe el acta.",
    ],
)
def test_negated_operations_and_nonexistence_do_not_claim_execution(text):
    assert not {"no_operational_claim", "no_nonexistence_inference"}.intersection(codes(text))


@pytest.mark.parametrize(
    "text",
    [
        "Según el oficio, se adjunta el acta.",
        "Se certifica que el taller fue aprobado.",
        "Se remitió el acta a la destinataria.",
        "No se afirma una entrega previa. Se adjunta el acta.",
        "No se puede confirmar una entrega previa, pero se entrega el acta.",
        "No se puede confirmar una entrega previa y se certifica que el taller fue aprobado.",
    ],
)
def test_positive_operations_cannot_hide_behind_negation(text):
    assert "no_operational_claim" in codes(text)


def test_absence_and_historical_petitions_remain_limited():
    assert "no_nonexistence_inference" in codes("No existe el acta solicitada.")
    assert "no_nonexistence_inference" in codes(
        "El antecedente registra una consulta. No existe el acta solicitada."
    )
    petition = {**HISTORY, "category": "historical_petition"}
    assert "petition_is_allegation" in codes(
        "Según el documento, el taller fue aprobado.", [petition]
    )
    assert "petition_is_allegation" not in codes(
        "El peticionario alegó en su solicitud que el taller fue aprobado.",
        [petition],
    )


def test_interface_preserves_input_and_legacy_issue_shape():
    sources = [deepcopy(HISTORY)]
    snapshot = deepcopy(sources)
    checks, issues = paragraph_claim_checks(
        "La docente dirigió el taller en 2025.",
        sources,
        paragraph_index=4,
    )
    assert sources == snapshot
    assert all(set(check) == {"code", "passed", "description"} for check in checks)
    assert all(set(issue) == {"code", "description", "paragraph_index"} for issue in issues)
    assert all(issue["paragraph_index"] == 4 for issue in issues)


@pytest.mark.parametrize(
    "text",
    [
        "En antecedentes históricos se dejó registrada la revisión del taller en 2022.",
        "El antecedente también precisó que el plan anual no acredita otra asignación.",
        "La consulta se refiere a determinar si la docente dirigió el taller en 2025. "
        "Este asunto es distinto de establecer quién preparó sus materiales.",
    ],
)
def test_plural_attribution_and_question_description(text):
    assert "historical_attribution" not in codes(text)


@pytest.mark.parametrize(
    "text",
    [
        "Su vigencia y aplicación al semestre 2025 deben cotejarse antes de concluir.",
        "La aplicación de la regla al semestre 2025 debe verificarse.",
    ],
)
def test_deferred_application_can_place_year_before_pending_predicate(text):
    assert "period_grounded" not in codes(text)


@pytest.mark.parametrize(
    "text",
    [
        "Según el antecedente, no estaba acreditada la asignación de 2022, "
        "mientras que la docente dirigió el taller en 2025.",
        "Según el antecedente, no estaba acreditada la asignación de 2025.",
        "La aplicación al semestre 2025 fue confirmada y debe verificarse otro período.",
        "No se puede confirmar la asignación y la docente fue titular en 2025.",
    ],
)
def test_negative_documentary_fact_is_not_a_general_limit(text):
    assert "period_grounded" in codes(text)


def test_current_limit_at_start_does_not_whitelist_current_negative_fact():
    assert "historical_current_fact" not in codes(
        "Actualmente no puede confirmarse que la cuenta pertenezca a la docente."
    )
    assert "historical_current_fact" in codes(
        "Según el antecedente, la docente no estaba autorizada actualmente para firmar."
    )


def test_question_object_date_does_not_ground_positive_claim():
    request = {"description": "Se pregunta por el conocimiento del correo de 2025."}
    assert "period_grounded" not in codes(
        "Sobre el conocimiento del correo de 2025, el antecedente señaló "
        "que no puede certificarse sin una declaración personal.",
        request=request,
    )
    assert "period_grounded" in codes(
        "Sobre el correo de 2025, el antecedente no permite concluir sobre su conocimiento. "
        "La docente dirigió el taller en 2025.",
        request=request,
    )


def test_draft_source_used_only_to_describe_a_question_is_not_promoted():
    assert "draft_status_preserved" not in codes(
        "La solicitud plantea si se había contestado la consulta.",
        [{**HISTORY, "document_status": "draft"}],
    )
    assert "draft_status_preserved" in codes(
        "La solicitud plantea si se había contestado la consulta. El oficio fue expedido.",
        [{**HISTORY, "document_status": "draft"}],
    )
    assert "draft_status_preserved" not in codes(
        "La solicitud plantea si se había contestado la consulta. "
        "También plantea verificar la autenticidad de las copias.",
        [{**HISTORY, "document_status": "draft"}],
    )
    assert "draft_status_preserved" in codes(
        "También plantea verificar la autenticidad de las copias, "
        "pero el documento fue expedido oficialmente.",
        [{**HISTORY, "document_status": "draft"}],
    )


def test_historical_remission_with_limit_does_not_claim_current_delivery():
    assert "no_operational_claim" not in codes(
        "Según el oficio de 2022, se remitió el acta en el trámite anterior, "
        "sin acreditar un envío actual."
    )
    assert "no_operational_claim" not in codes(
        "El oficio de 2022 indicó que se remitió el acta. "
        "Esa afirmación no acredita una entrega actual."
    )


@pytest.mark.parametrize(
    "text",
    [
        "Según el oficio de 2022, se adjunta el acta, sin acreditar otra entrega actual.",
        "Según el oficio de 2022, hemos remitido el acta, sin acreditar otra entrega actual.",
        "El oficio de 2022 no acredita un envío actual. Se remitió el acta a la destinataria.",
        "Según el oficio de 2022, se remitió el acta; sin acreditar un envío actual. "
        "Se adjunta el certificado al presente borrador.",
    ],
)
def test_historical_attribution_does_not_authorize_our_operations(text):
    assert "no_operational_claim" in codes(text)


@pytest.mark.parametrize(
    "text",
    [
        "Según el antecedente, se describió el alcance solicitado. El documento está "
        "identificado como borrador, por lo que este pasaje se incorpora únicamente "
        "como antecedente del trámite y no como una respuesta oficial expedida.",
        "En otro pasaje del oficio, identificado como borrador, se consignó una posición "
        "institucional. La afirmación describe la posición registrada en ese documento "
        "de trabajo; no confirma su aplicación a la solicitud actual.",
        "El borrador se incorpora como antecedente y no como respuesta oficial expedida.",
    ],
)
def test_draft_status_preserves_negated_issued_classification(text):
    assert "draft_status_preserved" not in codes(text, [{**HISTORY, "document_status": "draft"}])


@pytest.mark.parametrize(
    "text",
    [
        "El documento se presenta como borrador y no como una respuesta oficial expedida. "
        "Sin embargo, fue expedido oficialmente.",
        "El borrador se incorpora no como documento de trabajo, "
        "sino como una respuesta oficial expedida.",
        "El borrador se incorpora no como una respuesta oficial expedida, "
        "sino como oficio expedido.",
    ],
)
def test_negated_issued_classification_does_not_hide_another_positive_issuance(text):
    assert "draft_status_preserved" in codes(text, [{**HISTORY, "document_status": "draft"}])


def test_historical_attribution_without_draft_status_still_requires_it():
    text = (
        "En otro pasaje del mismo oficio, la institución consignó una posición. "
        "Esta afirmación describe lo registrado en ese antecedente; "
        "no confirma su aplicación a la solicitud actual."
    )
    assert "draft_status_preserved" in codes(text, [{**HISTORY, "document_status": "draft"}])


SCOPE_REQUEST = {
    "id": "Q7",
    "description": "Solicita la respuesta de la docente y los documentos del taller de 2022.",
}


@pytest.mark.parametrize(
    "text",
    [
        "Como alcance de la solicitud, se pide una respuesta completa, clara y de fondo "
        "de la docente, junto con los documentos relacionados con las peticiones. "
        "También se solicita la respuesta individual a las preguntas sobre la asignación "
        "en 2022, los actos de designación, el correo, la firma de calificaciones "
        "y la pertenencia de una cuenta electrónica.",
        "La pregunta consulta si la docente tuvo conocimiento personal del correo "
        "y, únicamente en caso afirmativo, si era correcta la presentación del remitente.",
        "La solicitud Q7 pide los documentos del taller.",
        "Se solicita copia del acta del taller; también se solicita una respuesta individual.",
        "La solicitud pide explicar la respuesta del comité sobre la plaza de prácticas. "
        "También solicita identificar los documentos de esa respuesta.",
        "La pregunta consulta, respecto del taller, sobre la asignación y los documentos. "
        "Este alcance delimita lo solicitado y no acredita por sí mismo "
        "ninguno de los hechos consultados.",
    ],
)
def test_only_current_request_scope_can_be_removed(text):
    assert is_request_scope_only(text, SCOPE_REQUEST)


@pytest.mark.parametrize(
    "text",
    [
        "La pregunta consulta por el taller. Según el oficio, la docente lo dirigió.",
        "La pregunta consulta por el taller, según el oficio anterior.",
        "El antecedente no acredita que la docente haya dirigido el taller.",
        "No existe el acta del taller.",
        "La pregunta consulta por el taller. La docente lo dirigió en 2022.",
        "La pregunta consulta por el taller, pero la docente lo dirigió en 2022.",
        "Se solicita el acta y se adjunta la copia.",
        "Se solicita el acta y quedó aprobada la asignación.",
        "Se solicita el acta porque la docente dirigió el taller.",
        "Según el oficio, se solicita copia del acta.",
        "El antecedente indicó: «Se solicita copia del acta».",
        "La solicitud anterior pide copia del acta.",
        "La solicitud Q8 pide los documentos del taller.",
        "También solicita identificar los documentos de esa respuesta.",
        "La solicitud pide explicar la respuesta del comité. "
        "También solicita identificar los documentos. La plaza está aprobada.",
        "La docente dirigió el taller en 2022.",
        "La pregunta consulta por el taller. No puede confirmarse su aprobación.",
        "La pregunta consulta por el taller. Este alcance delimita lo solicitado "
        "y no acredita por sí mismo ninguno de los hechos consultados. "
        "El acta fue aprobada.",
        "Se solicita.",
        "",
    ],
)
def test_request_scope_does_not_allow_removing_assertions_or_substantive_limits(text):
    assert not is_request_scope_only(text, SCOPE_REQUEST)


@pytest.mark.parametrize("context", [None, {}, {"id": "Q7"}, {"description": " "}])
def test_scope_removal_requires_current_request_context(context):
    assert not is_request_scope_only("Se solicita copia del acta.", context)


def test_scope_detection_preserves_request():
    request = deepcopy(SCOPE_REQUEST)
    assert is_request_scope_only("Se solicita copia del acta.", request)
    assert request == SCOPE_REQUEST
