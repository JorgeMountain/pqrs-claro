from pqrs_claro.models import Page
from pqrs_claro.preanalysis_engine import materialize


def ref(start, end=None):
    return dict(page=1, line_start=start, line_end=end or start)


def report():
    return {
        "requester": dict(
            state="pass", summary="Firma y canal indicados.", name="Isabel Mora",
            contact="isabel@example.invalid", refs=[ref(1)],
        ),
        "respect": dict(state="attention", summary="Descalifica a un tercero.", refs=[ref(3)]),
        "integrity": dict(state="pass", summary="Lectura completa.", refs=[]),
    }


def page(text):
    return [Page(number=1, text=text, method="native", needs_review=False)]


def test_misplaced_references_resolve_only_inside_explicit_sender_context():
    pages = page(
        "Al equipo de recepción.\nSolicito respuesta.\nEl proveedor es un idiota.\n"
        "Atte.: Isabel Mora\nFavor hacer llegar Respuesta en LOS email:\n\n"
        "isabel@example.invalid\nsegundo@example.invalid"
    )
    answer = report()
    answer["requester"]["contact"] = "isabel@example.invalid; segundo@example.invalid"
    checks = materialize(answer, pages)
    requester = checks["requester"]
    assert requester["state"] == "pass"
    assert requester["contact"] == "isabel@example.invalid"
    assert requester["name"] == "Isabel Mora"
    assert any(r["line_start"] == 4 and "Isabel Mora" in r["quote"] for r in requester["refs"])
    assert any(r["line_end"] == 7 and requester["contact"] in r["quote"]
               for r in requester["refs"])
    assert checks["respect"]["refs"][0]["quote"] == "El proveedor es un idiota."
    assert checks["integrity"]["state"] == "pass"


def test_uncited_third_party_address_is_not_assigned_to_the_sender():
    pages = page(
        "Atte.: Isabel Mora\nCopia a soporte: isabel@example.invalid\nEl proveedor es un idiota."
    )
    checks = materialize(report(), pages)
    assert checks["requester"]["name"] == "Isabel Mora"
    assert checks["requester"]["contact"] is None
    assert checks["requester"]["state"] == "unverified"
    assert checks["respect"]["state"] == "attention"
    assert checks["integrity"]["state"] == "pass"


def test_explicit_recipient_field_is_not_used_even_when_cited():
    pages = page(
        "Correo del destinatario: isabel@example.invalid\nAtte.: Isabel Mora\n"
        "El proveedor es un idiota."
    )
    answer = report()
    answer["requester"].update(name="ISABEL MORA", refs=[ref(1, 2)])
    requester = materialize(answer, pages)["requester"]
    assert requester["name"] == "Isabel Mora"
    assert requester["contact"] is None and requester["state"] == "unverified"


def test_backed_email_from_list_uses_entire_literal_address():
    pages = page(
        "Isabel Mora, m.isabel@example.invalid\nOtro canal: respuesta@example.invalid\n"
        "El proveedor es un idiota."
    )
    answer = report()
    answer["requester"].update(contact="isabel@example.invalid y respuesta@example.invalid",
                               refs=[ref(1, 2)])
    checks = materialize(answer, pages)
    assert checks["requester"]["state"] == "pass"
    assert checks["requester"]["contact"] == "respuesta@example.invalid"


def test_invalid_ranges_do_not_erase_other_verified_language_passages():
    pages = page("Isabel Mora\nisabel@example.invalid\nEl proveedor es un idiota.")
    answer = report()
    answer["requester"]["refs"] = [ref(1, 2)]
    answer["respect"]["refs"].append(ref(15))
    answer["integrity"]["refs"] = [ref(12)]
    checks = materialize(answer, pages)
    assert checks["requester"]["state"] == "pass"
    assert checks["respect"]["state"] == "attention"
    assert checks["respect"]["refs"] == [{**ref(3), "quote": "El proveedor es un idiota."}]
    assert checks["integrity"]["state"] == "unverified"
    assert checks["integrity"]["refs"] == []
