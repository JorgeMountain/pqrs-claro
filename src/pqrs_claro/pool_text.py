"""Texto del borrador compartido por la redacción y las correcciones administrativas."""


def reply_blocks(rows, letter=None):
    letter = letter or {}
    if letter.get("blocks"):
        # Keep the reviewed office's letterhead text, original petition fragments, shared
        # context, signature and attachments when a later contribution changes one answer.
        revised = {r["id"]: r for r in rows if "paragraphs" not in r}
        blocks = []
        for block in letter["blocks"]:
            ids = block.get("request_ids", [])
            kind = block["kind"]
            if (
                kind in {"response", "context", "conclusion"}
                and ids
                and all(k in revised for k in ids)
            ):
                continue
            blocks.append(block)
            if kind == "response_label" and ids and ids[0] in revised:
                blocks.append(
                    {
                        "kind": "response",
                        "text": revised[ids[0]]["answer"] or "Respuesta pendiente de respaldo.",
                    }
                )
        return [
            b
            for i, b in enumerate(blocks)
            if b["kind"] != "heading"
            or b.get("request_ids")
            or (
                i + 1 < len(blocks)
                and blocks[i + 1]["kind"] in {"context", "conclusion", "attachment"}
            )
        ]
    blocks = []
    if letter.get("requester"):
        blocks.append(dict(kind="recipient", text=letter["requester"]))
    subject = letter.get("subject")
    blocks.append(dict(
        kind="subject",
        text=f"Asunto: {subject}" if subject else "Asunto: Respuesta a su solicitud",
    ))
    if letter.get("reference"):
        blocks.append(dict(kind="metadata", text=f"Referencia: {letter['reference']}"))
    blocks.append(dict(kind="salutation", text="Cordial saludo."))
    blocks.append(dict(
        kind="intro",
        text=(
            "En atención a su solicitud, presentamos la respuesta "
            "a cada una de sus peticiones."
        ),
    ))
    for number, row in enumerate(rows, 1):
        blocks.append(dict(kind="request", text=f"{number}. {row['text']}"))
        blocks.append(dict(
            kind="response",
            text=row["answer"] or "Respuesta pendiente de respaldo.",
        ))
    return blocks


def reply_text(rows, letter=None):
    return "\n\n".join(block["text"] for block in reply_blocks(rows, letter))
