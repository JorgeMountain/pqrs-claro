"""Embeddings multilingües locales; complementan la búsqueda sin certificar hechos.

El modelo se instala explícitamente con ``python -m pqrs_claro.source_semantic
--download``. Importar este módulo o buscar no inicia descargas. Los vectores se
guardan en una base separada de los expedientes y sólo se puntúan los fragmentos
que el llamador ya autorizó para la consulta.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import sqlite3
import threading
import time
from collections import OrderedDict
from contextlib import closing
from pathlib import Path
from typing import Any, Callable

MODEL_NAME = "intfloat/multilingual-e5-small"
MODEL_REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"
MODEL_FILE = "onnx/model_qint8_avx512_vnni.onnx"
MODEL_SHA256 = "dd476dd0c2514e9b9be83aeb3853fac0763e0bdf4a71645407587d77c48a2d88"
MODEL_KEY = f"{MODEL_NAME}@{MODEL_REVISION}:{MODEL_FILE}:mean-l2:e5-prefix:v1"
DEFAULT_CACHE_DIR = Path("data/semantic")


def _model_path(cache_dir: Path) -> Path:
    return cache_dir / "models" / MODEL_REVISION


def download_model(cache_dir: Path = DEFAULT_CACHE_DIR) -> Path:
    """Descarga únicamente archivos públicos del modelo, en una revisión fija."""
    from huggingface_hub import snapshot_download

    target = _model_path(Path(cache_dir))
    snapshot_download(
        MODEL_NAME,
        revision=MODEL_REVISION,
        local_dir=target,
        allow_patterns=[
            MODEL_FILE,
            "config.json",
            "tokenizer.json",
            "tokenizer_config.json",
            "onnx/special_tokens_map.json",
        ],
    )
    # El repositorio publica este archivo junto al ONNX; FastEmbed lo busca
    # junto a tokenizer.json. Se copia literalmente, sin modificar el modelo.
    shutil.copyfile(
        target / "onnx" / "special_tokens_map.json", target / "special_tokens_map.json"
    )
    return target


def _load_model(cache_dir: Path, *, threads: int | None = None) -> Any:
    """Siempre offline, también cuando el modelo todavía no fue instalado."""
    model_path = _model_path(cache_dir)
    if not (model_path / MODEL_FILE).is_file():
        raise FileNotFoundError("modelo local no instalado")
    with (model_path / MODEL_FILE).open("rb") as file:
        if hashlib.file_digest(file, "sha256").hexdigest() != MODEL_SHA256:
            raise ValueError("La huella del modelo local no coincide con la revisión instalada")
    from fastembed import TextEmbedding
    from fastembed.common.model_description import ModelSource, PoolingType

    # FastEmbed documenta este registro para E5-small. Un nombre propio impide
    # confundir el ONNX cuantizado y fijado con otros archivos del mismo modelo.
    registered_name = "pqrs-claro/multilingual-e5-small-local-qint8"
    if not any(item["model"] == registered_name for item in TextEmbedding.list_supported_models()):
        TextEmbedding.add_custom_model(
            model=registered_name,
            pooling=PoolingType.MEAN,
            normalization=True,
            sources=ModelSource(hf=MODEL_NAME),
            dim=384,
            model_file=MODEL_FILE,
        )
    return TextEmbedding(
        model_name=registered_name,
        cache_dir=str(cache_dir / "models"),
        specific_model_path=str(model_path),
        local_files_only=True,
        threads=threads or max(1, min(4, (os.cpu_count() or 2) // 2)),
        providers=["CPUExecutionProvider"],
    )


def _document_text(chunk: dict[str, Any]) -> str:
    # Sólo contenido original y título. No incorporar evaluaciones, aprobaciones
    # ni hechos inferidos al vector que representa el documento.
    return f"{chunk.get('title', '')}\n{chunk.get('quote', '')}".strip()


def _text_key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class SemanticIndex:
    """Índice reutilizable por ejecución y persistente por huella de contenido.

    ``prepare`` permite indexar una vez, antes de recorrer los numerales.
    ``rank`` también prepara los fragmentos nuevos si hubo una actualización.
    Nunca devuelve contenido presente sólo en la caché y ausente de ``eligible``.
    Cualquier fallo desactiva este canal durante la instancia, conserva la caché
    parcial y deja una advertencia para que el servicio continúe con búsqueda léxica.
    """

    def __init__(
        self,
        cache_dir: Path | str = DEFAULT_CACHE_DIR,
        *,
        model_factory: Callable[[Path], Any] | None = None,
        model_key: str = MODEL_KEY,
        batch_size: int = 8,
        threads: int | None = None,
        matrix_cache_bytes: int = 64 * 1024 * 1024,
        preparation_budget_seconds: float | None = None,
        stop_event: threading.Event | None = None,
    ) -> None:
        if preparation_budget_seconds is not None and (
            not math.isfinite(preparation_budget_seconds) or preparation_budget_seconds < 0
        ):
            raise ValueError("El presupuesto de preparación debe ser finito y no negativo")
        self.cache_dir = Path(cache_dir)
        self.model_key = model_key
        self.batch_size = max(1, batch_size)
        self.warning: str | None = None
        self.diagnostics: dict[str, Any] = {
            "model": model_key,
            "cached": 0,
            "encoded": 0,
            "prepared": 0,
            "total": 0,
            "pending": 0,
            "complete": False,
            "budget_exhausted": False,
            "cancelled": False,
            "queries": 0,
            "matrix_builds": 0,
            "matrix_hits": 0,
            "matrix_cache_bytes": 0,
        }
        self._factory = model_factory or (lambda path: _load_model(path, threads=threads))
        self._model: Any = None
        self._vectors: dict[str, Any] = {}
        self._queries: OrderedDict[str, Any] = OrderedDict()
        self._matrices: OrderedDict[tuple[str, ...], Any] = OrderedDict()
        self._matrix_budget = max(0, matrix_cache_bytes)
        self._failed = False
        self._lock = threading.RLock()
        self._preparation_budget = preparation_budget_seconds
        self._preparation_deadline: float | None = None
        self._preparation_deferred = False
        self._stop_event = stop_event

    def _cancelled(self) -> bool:
        return bool(self._stop_event is not None and self._stop_event.is_set())

    def _progress(self, total: int, pending: int, progress=None) -> None:
        self.diagnostics.update(total=total, pending=pending, prepared=total - pending,
                                complete=pending == 0)
        if progress:
            progress(dict(self.diagnostics))

    def _complete(self, total: int, progress=None) -> None:
        self._preparation_deferred = False
        self.warning = None
        self.diagnostics.update(budget_exhausted=False, cancelled=False)
        self._progress(total, 0, progress)

    def _defer(self, *, cancelled: bool) -> None:
        self._preparation_deferred = True
        self.diagnostics.update(cancelled=cancelled, budget_exhausted=not cancelled)
        self.warning = (
            "La búsqueda por significado tiene cobertura parcial: "
            f"{self.diagnostics['prepared']} de {self.diagnostics['total']} fragmentos "
            "únicos preparados. "
            + ("La preparación se interrumpió. " if cancelled else
               "La preparación pendiente superó el tiempo disponible para esta consulta. ")
            + "La búsqueda por texto e identificadores conserva todo el alcance autorizado; "
            "la falta de una coincidencia no acredita ausencia documental. "
            "Los vectores terminados se conservan para completar el índice después."
        )

    def _embedding_model(self) -> Any:
        if self._model is None:
            self._model = self._factory(self.cache_dir)
        return self._model

    def _fail(self, error: Exception) -> None:
        self._failed = True
        self.warning = (
            "La búsqueda por significado no está disponible; se conserva la búsqueda "
            "por texto e identificadores. "
            f"Detalle: {type(error).__name__}: {error}"
        )

    @staticmethod
    def _normalize(vector: Any) -> Any:
        import numpy as np

        result = np.asarray(vector, dtype=np.float32)
        if result.ndim != 1 or not result.size or not np.isfinite(result).all():
            raise ValueError("El modelo produjo un vector inválido")
        norm = np.linalg.norm(result)
        if norm <= 0:
            raise ValueError("El modelo produjo un vector vacío")
        return result / norm

    def prepare(
        self,
        eligible: list[dict[str, Any]],
        *,
        progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> bool:
        """Reutiliza primero toda la caché autorizada y confirma cada lote nuevo.

        Sin presupuesto completa el corpus, como la preparación explícita por CLI.
        El modo interactivo comparte un único plazo entre todas sus llamadas;
        al agotarlo conserva los vectores y comunica cobertura parcial. El plazo
        se comprueba entre lotes, sin interrumpir una inferencia ONNX a medias.
        """
        with self._lock:
            if self._failed:
                return False
            if self._preparation_budget is not None and self._preparation_deadline is None:
                self._preparation_deadline = time.monotonic() + self._preparation_budget
            try:
                import numpy as np

                texts = {}
                for chunk in eligible:
                    text = _document_text(chunk)
                    texts[_text_key(text)] = text
                pending = set(texts).difference(self._vectors)
                if not pending:
                    self._complete(len(texts), progress)
                    return True
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                with closing(sqlite3.connect(
                    self.cache_dir / "embeddings.sqlite", timeout=60
                )) as connection, connection:
                    connection.execute(
                        "CREATE TABLE IF NOT EXISTS embeddings ("
                        "model_key TEXT NOT NULL, text_key TEXT NOT NULL, "
                        "dimensions INTEGER NOT NULL, "
                        "vector BLOB NOT NULL, PRIMARY KEY(model_key, text_key))"
                    )
                    # Use the composite primary key instead of loading every saved
                    # vector, including vectors outside the current collection.
                    pending_keys = sorted(pending)
                    for offset in range(0, len(pending_keys), 400):
                        batch = pending_keys[offset : offset + 400]
                        placeholders = ",".join("?" for _ in batch)
                        rows = connection.execute(
                            "SELECT text_key, dimensions, vector FROM embeddings "
                            f"WHERE model_key = ? AND text_key IN ({placeholders})",
                            (self.model_key, *batch),
                        )
                        for key, dimensions, value in rows:
                            vector = np.frombuffer(value, dtype="<f4")
                            if (len(vector) == dimensions and np.isfinite(vector).all()
                                    and vector.any()):
                                self._vectors[key] = self._normalize(vector)
                                pending.remove(key)
                                self.diagnostics["cached"] += 1
                        if self._cancelled():
                            self._progress(len(texts), len(pending))
                            self._defer(cancelled=True)
                            self._progress(len(texts), len(pending), progress)
                            return False
                    # Report the real cold-cache workload before the first ONNX batch.
                    # Even a zero budget loads every reusable, authorized vector.
                    self._progress(len(texts), len(pending), progress)
                    # El padding de ONNX alcanza el texto más largo del lote.
                    # Agrupar longitudes evita rellenar párrafos breves de DOCX
                    # hasta 512 tokens, sin recortar ni cambiar su contenido.
                    keys = sorted(pending, key=lambda key: (len(texts[key]), key))
                    for offset in range(0, len(keys), self.batch_size):
                        cancelled = self._cancelled()
                        if cancelled or (self._preparation_deadline is not None
                                         and time.monotonic() >= self._preparation_deadline):
                            self._defer(cancelled=cancelled)
                            self._progress(len(texts), len(keys) - offset, progress)
                            return False
                        batch = keys[offset : offset + self.batch_size]
                        vectors = list(
                            self._embedding_model().embed(
                                [f"passage: {texts[key]}" for key in batch],
                                batch_size=self.batch_size,
                            )
                        )
                        if len(vectors) != len(batch):
                            raise ValueError("El modelo no devolvió todos los fragmentos del lote")
                        rows = []
                        for key, vector in zip(batch, vectors, strict=True):
                            normalized = self._normalize(vector)
                            self._vectors[key] = normalized
                            rows.append(
                                (
                                    self.model_key,
                                    key,
                                    len(normalized),
                                    normalized.astype("<f4").tobytes(),
                                )
                            )
                        connection.executemany(
                            "INSERT OR REPLACE INTO embeddings VALUES (?, ?, ?, ?)", rows
                        )
                        connection.commit()
                        self.diagnostics["encoded"] += len(batch)
                        self._progress(len(texts), len(keys) - offset - len(batch), progress)
                self._complete(len(texts), progress)
                return True
            except Exception as error:
                self._fail(error)
                return False

    def rank(
        self, query: str, eligible: list[dict[str, Any]], limit: int = 60
    ) -> list[dict[str, Any]]:
        with self._lock:
            if self._failed or self._cancelled() or not query.strip() or not eligible or limit <= 0:
                return []
            try:
                import numpy as np

                keys = tuple(_text_key(_document_text(chunk)) for chunk in eligible)
                if not self._preparation_deferred and any(key not in self._vectors for key in keys):
                    self.prepare(eligible)
                if self._failed or self._cancelled():
                    return []
                # A bounded prepare must not be undone by rank implicitly encoding
                # the rest of the library. Only cached vectors in this call's scope
                # can contribute; metadata and citations still come from eligible.
                prepared = [(chunk, key) for chunk, key in zip(eligible, keys)
                            if key in self._vectors]
                if not prepared:
                    return []
                eligible = [chunk for chunk, _ in prepared]
                keys = tuple(key for _, key in prepared)
                matrix = self._matrices.get(keys)
                if matrix is None:
                    matrix = np.stack([self._vectors[key] for key in keys])
                    self.diagnostics["matrix_builds"] += 1
                    # Account for numeric storage and the key strings; cap the
                    # number of scopes too. Large scopes still work without caching.
                    size = matrix.nbytes + sum(len(key) + 64 for key in keys) + 128
                    if size <= self._matrix_budget:
                        while self._matrices and (
                            self.diagnostics["matrix_cache_bytes"] + size > self._matrix_budget
                            or len(self._matrices) >= 4
                        ):
                            old_keys, old_matrix = self._matrices.popitem(last=False)
                            self.diagnostics["matrix_cache_bytes"] -= (
                                old_matrix.nbytes + sum(len(key) + 64 for key in old_keys) + 128
                            )
                        self._matrices[keys] = matrix
                        self.diagnostics["matrix_cache_bytes"] += size
                else:
                    self._matrices.move_to_end(keys)
                    self.diagnostics["matrix_hits"] += 1
                if query not in self._queries:
                    vectors = list(self._embedding_model().embed([f"query: {query}"], batch_size=1))
                    if len(vectors) != 1:
                        raise ValueError("El modelo no devolvió el vector de la consulta")
                    self._queries[query] = self._normalize(vectors[0])
                    self.diagnostics["queries"] += 1
                    if len(self._queries) > 128:
                        self._queries.popitem(last=False)
                self._queries.move_to_end(query)
                # Matrices cache only vectors in eligible order, never metadata.
                # Current identifiers, permissions and citations come from eligible.
                scores = matrix @ self._queries[query]
                positions = sorted(
                    range(len(eligible)),
                    key=lambda index: (
                        -float(scores[index]),
                        str(eligible[index].get("chunk_id", "")),
                    ),
                )[:limit]
                return [
                    {**eligible[index], "semantic_score": round(float(scores[index]), 8)}
                    for index in positions
                ]
            except Exception as error:
                self._fail(error)
                return []


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument(
        "--threads", type=int, default=None, help="Hilos de CPU para la preparación"
    )
    parser.add_argument("--download", action="store_true", help="Instalar el modelo público local")
    parser.add_argument(
        "--chunks", type=Path, help="JSON de fragmentos para preparar el índice local"
    )
    args = parser.parse_args()
    if args.threads is not None and args.threads < 1:
        parser.error("--threads debe ser un entero positivo")
    if args.download:
        print(f"Modelo instalado: {download_model(args.cache_dir)}", flush=True)
    if args.chunks:
        chunks = json.loads(args.chunks.read_text(encoding="utf-8"))
        index = SemanticIndex(args.cache_dir, threads=args.threads)
        last_report = 0.0

        def report_progress(info: dict[str, Any]) -> None:
            nonlocal last_report
            current = time.monotonic()
            if current - last_report >= 10:
                print(json.dumps(info), flush=True)
                last_report = current

        ok = index.prepare(chunks, progress=report_progress)
        print(json.dumps({"ok": ok, "warning": index.warning, **index.diagnostics}), flush=True)
        if not ok:
            raise SystemExit(1)
    if not args.download and not args.chunks:
        parser.print_help()


if __name__ == "__main__":
    main()
