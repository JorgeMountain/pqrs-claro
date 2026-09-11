"""Fragmentos de la petición por coordenada, sin resumir ni alterar su texto."""

from .models import DomainError
from .office_models import xml_text


def request_fragments(request: dict) -> list[dict]:
    """Ordena citas y reúne líneas contiguas; una coordenada conserva un único texto."""
    refs = request.get("source_refs")
    if refs is None:
        return []
    if not isinstance(refs, list):
        raise DomainError("Las referencias originales de la petición no tienen un formato válido.")
    lines = {}
    for ref in refs:
        if not isinstance(ref, dict):
            raise DomainError("Una referencia original de la petición no tiene un formato válido.")
        page, start, end = (ref.get(key) for key in ("page", "line_start", "line_end"))
        if any(type(value) is not int or value < 1 for value in (page, start, end)) or end < start:
            raise DomainError("Una referencia original de la petición tiene coordenadas inválidas.")
        quote = ref.get("quote")
        if not isinstance(quote, str) or not quote.strip() or "\r" in quote:
            raise DomainError("Una cita original no conserva texto y saltos de línea válidos.")
        try:
            xml_text(quote)
        except ValueError as exc:
            raise DomainError(str(exc)) from None
        # source_quote guarda las líneas canónicas con LF. split("\n") conserva
        # también la última línea vacía, que forma parte de su rango inclusivo.
        quoted_lines = quote.split("\n")
        if len(quoted_lines) != end - start + 1:
            raise DomainError(
                "El texto de una cita original no coincide con su cantidad de líneas."
            )
        for number, text in enumerate(quoted_lines, start):
            coordinate = (page, number)
            if coordinate in lines and lines[coordinate] != text:
                raise DomainError(
                    "Las citas originales contienen textos contradictorios "
                    f"en la página {page}, línea {number}."
                )
            lines[coordinate] = text

    fragments = []
    current_lines = []
    for (page, number), text in sorted(lines.items()):
        if (
            not fragments
            or page != fragments[-1]["page"]
            or number != fragments[-1]["line_end"] + 1
        ):
            if fragments:
                fragments[-1]["text"] = "\n".join(current_lines)
            fragments.append({"text": "", "page": page, "line_start": number, "line_end": number})
            current_lines = []
        fragments[-1]["line_end"] = number
        current_lines.append(text)
    if fragments:
        fragments[-1]["text"] = "\n".join(current_lines)
    return fragments
