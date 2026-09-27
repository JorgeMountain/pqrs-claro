"""JEV chooses each petition type; OpenAI handles the other intake checks."""

import json
from concurrent.futures import ThreadPoolExecutor

import httpx

from .classification_questions import QUESTIONS
from .intake_engine import OpenAIIntakeEngine
from .intake_models import IntakeAssessment, IntakeContextAssessment
from .jev_client import ENDPOINT, MODEL, get_key
from .models import DomainError, Page, source_quote

CLASSIFICATION_VERSION = 1
MAX_BATCH_BYTES = 24000
# Larger batches returned provider HTTP 503 in live checks; pairs covered all ten
# sample petitions successfully. This is a conservative workaround, not an API limit.
MAX_BATCH_REQUESTS = 2
MAX_CONCURRENT_BATCHES = 2
TYPE_NAMES = {
    "information": "Información",
    "documents": "Documentos",
    "individual": "Interés particular",
    "general": "Interés general",
    "consultation": "Consulta",
    "complaint": "Queja",
    "claim": "Reclamo",
    "suggestion": "Sugerencia",
    "denunciation": "Denuncia",
    "congratulation": "Felicitación",
    "undetermined": "Por determinar",
}


def probability(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
        raise ValueError("Invalid probability")
    return value


class JevPetitionClassifier:
    def __init__(self, *, key=None, transport=None):
        self.key = get_key() if key is None else key
        self.transport = transport

    @staticmethod
    def body(requests):
        return {
            "model": MODEL,
            "state": {"requests": requests},
            "questions": {
                r["id"]: {
                    **QUESTIONS["petition_type"],
                    "instructions": (
                        f"Evaluate ONLY the petition with id {r['id']} in state.requests. "
                        "Use its identified title and description to locate the specific intent "
                        "in its original excerpts; an excerpt may also contain other petitions. "
                        + QUESTIONS["petition_type"]["instructions"]
                    ),
                }
                for r in requests
            },
        }

    def classify(self, payload):
        if not self.key:
            raise DomainError(
                "Configura AI_GATEWAY_API_KEY en .env.jev.local para clasificar con JEV."
            )
        pages = [Page.model_validate(p) for p in payload["pages"]]
        requests = []
        for r in payload["identification"]["requests"]:
            requests.append(
                {
                    "id": r["id"],
                    "title": r["title"],
                    "description": r["description"],
                    "original_excerpts": [
                        source_quote(
                            pages, **{k: ref[k] for k in ("page", "line_start", "line_end")}
                        )
                        for ref in r["source_refs"]
                    ],
                }
            )
        # Limit each batch explicitly. Never truncate a identified petition or its excerpts.
        batches, batch = [], []
        for request in requests:
            candidate = batch + [request]
            size = len(json.dumps(self.body(candidate), ensure_ascii=False).encode("utf-8"))
            if len(candidate) > MAX_BATCH_REQUESTS or size > MAX_BATCH_BYTES:
                if batch:
                    batches.append(batch)
                batch = [request]
                if (
                    len(json.dumps(self.body(batch), ensure_ascii=False).encode("utf-8"))
                    > MAX_BATCH_BYTES
                ):
                    raise DomainError(
                        f"La petición {request['id']} supera el tamaño admitido por JEV. "
                        "Delimita sus fragmentos en la identificación; no se ha recortado el texto."
                    )
            else:
                batch = candidate
        if batch:
            batches.append(batch)
        decisions = {}
        try:
            with httpx.Client(timeout=90, trust_env=False, transport=self.transport) as client:
                with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_BATCHES) as pool:
                    for result in pool.map(
                        lambda batch: self.classify_batch(client, batch), batches
                    ):
                        decisions.update(result)
        except httpx.RequestError:
            raise DomainError(
                "No se pudo conectar con JEV para clasificar las peticiones."
            ) from None
        except (KeyError, ValueError, TypeError, AttributeError) as exc:
            if isinstance(exc, DomainError):
                raise
            raise DomainError(
                "JEV devolvió una clasificación incompleta o inválida. Reintenta."
            ) from None
        return decisions

    def classify_batch(self, client, batch):
        decisions = {}
        response = client.post(
            ENDPOINT,
            headers={"Authorization": f"Bearer {self.key}"},
            json=self.body(batch),
        )
        # Some pairs also return 503 while the same petitions succeed individually.
        # Retry only that pair, with the same provider and complete original excerpts.
        if response.status_code == 503 and len(batch) > 1:
            for request in batch:
                decisions.update(self.classify_batch(client, [request]))
            return decisions
        if response.status_code != 200:
            try:
                error = response.json().get("error", {})
            except (ValueError, AttributeError):
                error = {}
            if (
                isinstance(error, dict)
                and error.get("type") == "no_providers_available"
                and "Free tier users do not have access" in str(error.get("message", ""))
            ):
                raise DomainError(
                    "Vercel no permite usar JEV con créditos gratuitos en este momento. "
                    "Habilita créditos de pago o configura otro clasificador antes de reintentar."
                )
            reason = (
                "El servicio de JEV no está disponible temporalmente. "
                "Reintenta el análisis más tarde."
                if response.status_code == 503
                else ("Revisa la conexión, la clave o el saldo de AI Gateway y reintenta.")
            )
            raise DomainError(f"JEV no pudo clasificar (HTTP {response.status_code}). {reason}")
        answers = response.json()["answers"]
        if set(answers) != {r["id"] for r in batch}:
            raise ValueError("Incomplete decision batch")
        for request in batch:
            answer = answers[request["id"]]
            choice = answer["choice"]
            if answer.get("type") != "choice" or choice not in TYPE_NAMES:
                raise ValueError("Invalid decision")
            probabilities = answer["probabilities"]
            if set(probabilities) != set(TYPE_NAMES):
                raise ValueError("Incomplete probability distribution")
            clean = {k: probability(v) for k, v in probabilities.items()}
            if abs(sum(clean.values()) - 1) > 0.05:
                raise ValueError("Invalid distribution")
            decisions[request["id"]] = {
                "choice": choice,
                "confidence": probability(answer["confidence"]),
                "probabilities": clean,
            }
        return decisions


class JevIntakeEngine:
    def __init__(self, settings, *, context_engine=None, classifier=None):
        self.context_engine = context_engine or OpenAIIntakeEngine(settings, context_only=True)
        self.classifier = classifier or JevPetitionClassifier()

    def assess(self, payload):
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="intake-analysis") as pool:
            classification = pool.submit(self.classifier.classify, payload)
            document = pool.submit(self.context_engine.assess, payload)
            decisions = classification.result()
            context = IntakeContextAssessment.model_validate(document.result()).model_dump(
                mode="json"
            )
        originals = {r["id"]: r for r in payload["identification"]["requests"]}
        ids = [r["request_id"] for r in context["requests"]]
        if (
            len(ids) != len(set(ids))
            or set(ids) != set(originals)
            or set(decisions) != set(originals)
        ):
            raise DomainError("La revisión no cubre exactamente las peticiones identificadas.")
        for row in context["requests"]:
            decision = decisions[row["request_id"]]
            undetermined = decision["choice"] == "undetermined"
            row.update(
                petition_type=decision["choice"],
                classification_model=MODEL,
                classification_confidence=decision["confidence"],
                classification_probabilities=decision["probabilities"],
            )
            row["checks"].append(
                {
                    "key": "classification",
                    "state": "unverified" if undetermined else "no_observation",
                    "summary": f"Tipo sugerido por JEV: {TYPE_NAMES[decision['choice']]}.",
                    "reason": (
                        "JEV evaluó el título, la descripción identificada "
                        "y sus fragmentos originales. Los fragmentos mostrados "
                        "son parte de la entrada, no una explicación generada "
                        "por el modelo. El tipo requiere confirmación humana."
                    ),
                    "original_refs": [
                        {k: ref[k] for k in ("page", "line_start", "line_end")}
                        for ref in originals[row["request_id"]]["source_refs"][:12]
                    ],
                    "chunk_ids": [],
                    "pending": ["Determinar el tipo de petición antes de continuar."]
                    if undetermined
                    else [],
                }
            )
        return IntakeAssessment.model_validate(context)
