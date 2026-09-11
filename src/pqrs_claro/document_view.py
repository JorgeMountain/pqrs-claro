"""Vista del original con marcas derivadas de las citas guardadas del expediente."""

import pymupdf
from fastapi import APIRouter, HTTPException


def document_view_router(cases):
    router = APIRouter()

    @router.get("/api/cases/{case_id}/pages/{number}/view")
    def page_view(case_id: str, number: int, request_id: str | None = None):
        case = cases.get(case_id)
        selected = None
        if request_id:
            selected = next(
                (
                    r
                    for r in (case.get("identification") or {}).get("requests", [])
                    if r["id"] == request_id
                ),
                None,
            )
            if selected is None:
                raise HTTPException(404, "La solicitud no pertenece a este expediente.")
        with pymupdf.open(cases.original(case_id)) as doc:
            if not 1 <= number <= len(doc):
                raise HTTPException(404, "La página no existe.")
            page = doc[number - 1]
            refs = [ref for ref in (selected or {}).get("source_refs", []) if ref["page"] == number]
            marks = []
            for ref in refs:
                quote = " ".join(ref["quote"].split())
                marks.append(
                    dict(
                        quote=ref["quote"],
                        rectangles=[list(rect) for rect in page.search_for(quote)] if quote else [],
                    )
                )
            extracted = next((p for p in case.get("pages", []) if p["number"] == number), {})
            return dict(
                case_id=case_id,
                version=case["version"],
                page=number,
                page_count=len(doc),
                width=page.rect.width,
                height=page.rect.height,
                text=extracted.get("text", ""),
                marks=marks,
                request_id=request_id,
                has_visual_match=any(m["rectangles"] for m in marks),
            )

    return router
