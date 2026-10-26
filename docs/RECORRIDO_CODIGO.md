# Recorrido del código de PQRS Claro

Para instalar y entregar la versión actual, usa [ENTREGA.md](ENTREGA.md) y el
[índice de documentación](README.md). La interfaz actual tiene cuatro etapas:
Preanálisis, Identificación, Redacción y Borrador.

**Lectura actualizada del 12 de octubre de 2026:** empieza por la
[guía para entender y colaborar](GUIA_PARA_ENTENDER_Y_COLABORAR.md).
La bandeja ahora separa recepción e inicio del análisis; se incorporaron revisión
inicial, gestión y una excepción explícita de piloto. La secuencia inicial y el
modelo predeterminado mencionados más abajo corresponden a la etapa de esta guía.

Guía comprobada contra el código del repositorio el **15 de septiembre de 2026**. Explica el recorrido elegido en **8772**. Los ejemplos de esta guía son didácticos: no ejecutan IA ni cambian expedientes.

**Ampliación del 16 de septiembre:** hay una segunda entrada por Gmail junto a la
carga de PDF. `gmail_auth.py` conecta la cuenta; `gmail_service.py` conserva el correo
y crea o vincula el expediente; después se utiliza el mismo flujo descrito aquí.
Consulta [GMAIL.md](GMAIL.md) para configurar la conexión y conocer su alcance.

**Actualización del 19 de septiembre:** interfaz y API funcionan en un solo proceso
en 8772. Los comandos `start.ps1` y `start-recorrido.ps1` usan ese modo.

## 1. La idea central

El sistema transforma un PDF en solicitudes individuales y prepara respuestas con sus soportes. El navegador muestra y permite editar; Python coordina los procesos y aplica las reglas; la IA identifica, evalúa y redacta; SQLite y los archivos locales conservan el trabajo.

```text
Tú, en el navegador
        │ clic, archivo o edición
        ▼
Interfaz 8772 — HTML, CSS y JavaScript
        │ /api/… → rutas de la misma aplicación
        ▼
API 8772 — unified_app.py, app.py y módulos *_api.py
        │
        ├── Servicios: coordinan operaciones y comprueban versiones
        ├── Grafos: ordenan pasos, guardan avance y permiten pausas
        ├── Motores: interpretan o redactan con IA + validaciones locales
        └── Almacenamiento: SQLite + documentos originales + exportaciones
```

**La interfaz y la API comparten un solo proceso en 8772 y las mismas bases.** El puerto 8770 ya no es necesario para el arranque habitual. El proxy anterior se conserva en `recorrido_app.py` para recuperación explícita. `langgraph-pqrs/` es otro proyecto del directorio padre.

El flujo real actual no depende de n8n. Tampoco hay una consulta automática a OnBase: la recuperación se hace sobre las fuentes incorporadas y habilitadas en la biblioteca local.

## 2. Dónde está cada cosa

Las rutas de esta guía parten de `pqrs-claro/`. El código Python está en `src/pqrs_claro/`.

| Carpeta o archivo | Qué contiene | Cuándo lo abrirías |
|---|---|---|
| `scripts/start-recorrido.ps1` | Arranque unificado, compartido con `start.ps1` | Para levantar la página de 8772 |
| `src/pqrs_claro/unified_app.py` | Entrada de la aplicación unificada | Para entender el arranque en un puerto |
| `src/pqrs_claro/recorrido_ui.py` | Montaje de los recursos de la interfaz después de la API | Para revisar rutas estáticas |
| `src/pqrs_claro/recorrido_app.py` | Proxy anterior, conservado como alternativa | Para una recuperación explícita del modo anterior |
| `src/pqrs_claro/static/recorrido/` | La interfaz elegida: pantallas, eventos y estilos | Para modificar tarjetas, editor o interacción |
| `src/pqrs_claro/app.py` | Construcción de la aplicación, servicios y rutas | Para entender cómo se conecta todo |
| `src/pqrs_claro/preparation.py` | Coordinación de fuentes → pendientes → borradores | Para cambiar cuándo comienza cada proceso |
| `src/pqrs_claro/models.py` y `*_models.py` | Formato de solicitudes, párrafos, revisiones y oficios | Para entender qué datos acepta el sistema |
| `src/pqrs_claro/config.py` | Modelo, límites, ubicación de datos y lectura de configuración | Para configurar el backend |
| `data/` | Expedientes, fuentes, originales, revisiones y checkpoints | Para comprender persistencia; no editar a mano |
| `tests/` | Pruebas de reglas y flujos con datos controlados | Para ver ejemplos de comportamiento esperado |
| `examples/` | Casos ficticios y documentos de prueba | Para practicar |
| `docs/` | Alcance y decisiones de implementación | Para contrastar el diseño |
| `output/` | Resultados auxiliares y comprobaciones locales | Para consultar artefactos de desarrollo |

Hay otras interfaces en `static/workspace/` y directamente en `static/`. Para cambiar la experiencia que elegiste, empieza por **`static/recorrido/`**; algunos módulos compartidos se importan desde `static/`.

## 3. Cómo leer los nombres de los módulos

No necesitas memorizar todos los archivos. La terminación suele explicar su responsabilidad:

| Nombre | Responsabilidad | Ejemplo |
|---|---|---|
| `*_api.py` | Recibe una petición HTTP, valida su formato y llama al servicio | `review_api.py` |
| `*_service.py` | Aplica reglas, coordina trabajo y guarda resultados | `draft_service.py` |
| `*_graph.py` | Define el orden de los pasos y sus bifurcaciones | `draft_graph.py` |
| `*_engine.py` | Ejecuta razonamiento/redacción y comprobaciones | `draft_engine.py` |
| `*_store.py` | Lee y escribe registros persistentes | `review_store.py` |
| `*_models.py` | Declara campos y restricciones de datos | `office_models.py` |

Excepciones útiles: `service.py`, `workflow.py` y `storage.py` corresponden a la primera etapa; `source_assessment.py` contiene el evaluador de fuentes; `source_library.py` administra biblioteca y persistencia de fuentes.

**FastAPI** conecta URLs con funciones Python. **Pydantic** comprueba la estructura de los datos. **LangGraph** conecta pasos y guarda puntos de reanudación. **SQLite** guarda registros en archivos locales. Son responsabilidades distintas.

## 4. Sigue una petición de principio a fin

Ejemplo ficticio continuo: «Indicar quién estuvo a cargo de una asignatura en un semestre y aportar el registro que lo acredita». El ejemplo no presupone que ese registro esté disponible.

### Parada 1 · Cargas el PDF

- Pantalla: `static/recorrido/petition-upload.js` y `live.js`.
- En `live.js`, `upload(file)` envía el archivo mediante `POST /api/cases` y después solicita `POST /api/cases/{id}/analyze`.
- `app.py` verifica que sea un PDF admisible; `CaseStore.create()` en `storage.py` conserva `data/files/{id}/original.pdf`, calcula su SHA-256 y crea el expediente.
- La copia original se conserva separada del texto extraído. La huella permite detectar si el archivo cambió.

**Resultado:** un expediente con identificador y estado inicial `uploaded`. Cargar el archivo todavía no equivale a haber comprendido sus solicitudes.

### Parada 2 · Lee e identifica

Abre [`workflow.py`](../src/pqrs_claro/workflow.py), función `build_graph()`. Es el mejor primer archivo para entender LangGraph:

```text
read_pdf → identify_requests → review_identification → fin
                                     ↑ pausa humana
```

- `service.py` ejecuta ese grafo en segundo plano.
- `extraction.py` obtiene texto por página con PyMuPDF y recurre a OCR cuando hace falta. En el análisis de peticiones, el proveedor OCR configurado es OpenAI.
- `identification.py` pide a la IA solicitudes estructuradas y sus ubicaciones en las páginas.
- `models.py` valida la identificación y sus referencias.
- `review_identification` usa `interrupt()` para esperar tu confirmación; el avance queda guardado.
- `document_view.py` y `static/recorrido/original-viewer.js` permiten contrastar la solicitud con el original y su resaltado.

**Resultado:** tarjetas editables para revisar lo que se identificó. No son aún respuestas.

En el flujo actual, `intake_service.py` continúa con `petition_classification.py` para proponer el tipo de cada petición usando sus fragmentos originales. Esta etapa conserva el preanálisis y no carga ni busca en la biblioteca. Las clasificaciones nuevas no se invalidan por añadir fuentes; los análisis anteriores conservan su contrato y su historial.

### Parada 3 · Confirmas las solicitudes

En [`static/recorrido/live.js`](../src/pqrs_claro/static/recorrido/live.js), busca `case 'live-initial-confirm'`.

```text
Revisión conjunta de todas las peticiones y sus tipos
  → PUT /api/cases/{id}/initial-review/decision
  → decisión del gestor guardada
  → POST /api/cases/{id}/preparation
  → Redacción: busca fuentes, revisa pendientes y prepara respuestas
```

[`preparation.py`](../src/pqrs_claro/preparation.py) es el coordinador principal de esta parte. `run()` espera el análisis de fuentes, construye los pendientes y manda a redactar las solicitudes elegibles.

Confirmar aquí significa «estas son las solicitudes del PDF». **No aprueba una respuesta ni certifica las fuentes.**

### Parada 4 · Busca candidatos en la biblioteca

- `source_library.py`: conserva originales, texto extraído, versiones, colecciones y fragmentos.
- `SourceLibrary.eligible()`: filtra las fuentes que el expediente puede consultar.
- `source_context.py`: incorpora contexto útil de la petición.
- [`source_retrieval.py`](../src/pqrs_claro/source_retrieval.py), función `retrieve()`: recupera fragmentos candidatos.
- `source_semantic.py`: añade búsqueda semántica local cuando el modelo está disponible; existe continuidad por búsqueda textual si no está disponible.

La recuperación combina coincidencias de texto, contexto, identificadores de documentos, entidades y significado. También puede recuperar la contestación contigua a una pregunta de un oficio histórico. El límite actual es de **24 fragmentos candidatos por solicitud**.

Al crear un expediente se vinculan las colecciones existentes por defecto. Eso no elimina los filtros: se excluyen, por ejemplo, versiones sustituidas y categorías no elegibles. «Todas las fuentes seleccionadas» no significa que cada archivo se use como prueba en cada respuesta.

**Resultado:** documentos potencialmente útiles. Encontrar una mención al profesor no demuestra todavía una asignación docente concreta.

### Parada 5 · Evalúa qué respaldan esos pasajes

[`source_graph.py`](../src/pqrs_claro/source_graph.py) contiene dos nodos:

```text
retrieve_sources → assess_sources
```

`source_assessment.py` envía los candidatos a la IA para evaluar pertinencia, roles y cobertura. La IA devuelve selecciones estructuradas. **El programa obtiene la cita a partir de su ubicación**, en vez de pedirle al modelo que vuelva a escribirla:

```text
IA: fragmento C2, líneas 3–5
Python: toma exactamente esas líneas del texto extraído
Validación: comprueba rango, identidad, ámbito y uso del soporte
```

La implementación está en [`source_passages.py`](../src/pqrs_claro/source_passages.py), `numbered_lines()` y `resolve_passages()`. Las líneas son locales al fragmento, no números absolutos de la página. Una copia exacta del texto extraído tampoco garantiza fidelidad visual si hubo OCR.

`source_sufficiency.py` y `evidence_contract.py` ayudan a convertir la evaluación en cobertura y pendientes concretos. Un oficio anterior puede ser un antecedente sin acreditar por sí solo el hecho actual, la expedición oficial o la entrega de un anexo.

**Resultado:** soportes seleccionados, cobertura, puntos por resolver o error de análisis.

### Parada 6 · Resuelves pendientes antes de redactar

- Pantalla: `static/recorrido/live-pending.js` y `live-pending-view.js`.
- Recepción de decisiones: `review_api.py`.
- Reglas y conservación: `review_service.py`, `evidence_contract.py` y `document_decisions.py`.
- Nuevos archivos: `evidence_api.py`, con actualización de fuentes desde el recorrido.

La revisión inicial se crea con `before_draft=True`. Así puedes ver qué hace falta antes de que exista una respuesta.

Para el ejemplo, si el registro no está disponible, el sistema puede pedir evidencia o una comprobación concreta. Confirmar, justificar que un pendiente no aplica y aportar evidencia son operaciones distintas. Una búsqueda sin resultado no demuestra que el documento no exista.

Cuando guardas una resolución previa al borrador, `review_api.py` llama a `PreparationService.decision_saved()`. El coordinador comprueba si ya puede continuar.

Abre `DraftService._ready_for_draft()` en [`draft_service.py`](../src/pqrs_claro/draft_service.py). Para la redacción inicial exige:

- Entradas vigentes, sin cambio pendiente de actualizar.
- Ausencia de error de análisis.
- Ningún pendiente bloqueante abierto.
- Que todavía no haya párrafos redactados.

**Resultado:** una solicitud puede avanzar mientras otra sigue esperando evidencia. Resolver un pendiente no equivale a aprobar el oficio.

### Parada 7 · Redacta y comprueba

[`draft_graph.py`](../src/pqrs_claro/draft_graph.py) expresa el proceso de cada solicitud:

```text
planificar → redactar → comprobar
                          ├─ sin ajuste previsto → fin
                          └─ ajustar_citas → recomprobar → fin
```

El ajuste está acotado y puede ser rechazado; no es un bucle ilimitado. `draft_engine.py` implementa `plan()`, `write()`, `check()` y `repair()`. Los párrafos mantienen referencias a sus soportes. `draft_claim_checks.py` aporta controles locales sobre afirmaciones.

**Paralelismo actual:** `source_service.py` analiza hasta tres solicitudes simultáneamente y `draft_service.py` redacta hasta tres elegibles simultáneamente, según configuración. Cada solicitud conserva el orden de sus pasos. La preparación espera la etapa de fuentes antes de organizar pendientes y redacción; no hay que confundir paralelismo entre solicitudes con ejecutar todo el expediente a la vez.

**Resultado:** propuestas de respuesta comprobadas, con posibilidad de ajustes pendientes. La IA no concede aprobación final.

### Parada 8 · Editas respuestas o pides una propuesta

`static/recorrido/live-edit.js` permite editar la respuesta y `review_service.py` conserva el cambio. La aprobación y evaluación anteriores dejan de valer si cambió su contenido o respaldo relevante.

`static/recorrido/live-proposal.js`, `response_proposals.py` y `response_proposal_engine.py` implementan la propuesta de actualización con IA y su aplicación o descarte.

**Editar y guardar no son sinónimos de pedir una nueva redacción.** La comprobación evalúa tu texto; la propuesta de IA es otra operación.

### Parada 9 · Editas el oficio completo

El paso 3 actual utiliza [`static/recorrido/live-document.js`](../src/pqrs_claro/static/recorrido/live-document.js). Su `createFinal()` construye el editor. `document-tools.js` aporta las herramientas y el zoom.

```text
GET /api/cases/{id}/office/workspace → oficio ensamblado
Edición en el navegador             → cambios aún locales
PUT /api/cases/{id}/office/workspace → guardado
POST …/review/requests/{rid}/assess  → comprobaciones pendientes
```

`office_workspace.py`, función `save_workspace()`, guarda metadatos y respuestas con control de revisiones en una transacción. Si detecta un conflicto, evita un guardado parcial.

En `live-document.js`, `save()` conserva los cambios y llama a `check()`. Esta última solicita comprobaciones sobre las respuestas que las necesitan. **No llama al motor de redacción para rehacer todo el documento.** Cancelar vuelve a cargar lo guardado. Los cambios que solo están en el editor todavía no equivalen a una versión persistida.

### Parada 10 · Generas Word o PDF

En el editor, `generate()` exige contenido guardado y comprobaciones vigentes. La acción de generar aprueba explícitamente las respuestas listas que forman el oficio y solicita una vista previa y la generación.

- `office_api.py`: rutas de vista previa, generación y descargas.
- `office_service.py`: valida la versión aprobada y coordina la generación.
- `office_renderer.py`: construye y verifica el documento con el texto guardado.
- `office_templates.py`: membrete y plantilla.
- `office_word.py`: conversión local mediante Word de escritorio.
- `office_store.py`: historial de generaciones.

**Resultado:** Word, PDF y, si corresponde, paquete de anexos. Exportar no reescribe con IA ni envía el oficio a OnBase o al destinatario.

## 5. Qué se guarda y por qué se puede continuar

| Persistencia local | Contenido principal |
|---|---|
| `data/expedientes.sqlite` | Expediente, versiones y preparación |
| `data/biblioteca.sqlite` | Catálogo de fuentes y ejecuciones de análisis |
| `data/borradores.sqlite` | Ejecuciones y resultados de redacción |
| `data/revisiones.sqlite` | Respuestas editadas, decisiones, historial y área de trabajo del oficio |
| `data/oficios.sqlite` | Generaciones del oficio |
| `data/checkpoints.sqlite` | Avance del grafo de identificación |
| `data/source_checkpoints.sqlite` | Avance del grafo de fuentes |
| `data/draft_checkpoints.sqlite` | Avance del grafo de redacción |
| `data/review_checkpoints.sqlite` | Avance del grafo de revisión/aprobación |
| Documentos en `data/` | Originales y artefactos de los expedientes |

El checkpoint responde «¿en qué paso iba el proceso?». Los registros de negocio responden «¿cuál es la solicitud, respuesta o decisión guardada?». Por eso existen ambos.

Cerrar la pestaña no detiene por sí mismo al servidor. Apagar o reiniciar el servidor sí interrumpe sus trabajadores: al volver, los servicios reconocen ejecuciones incompletas y permiten continuar. No es un servicio en la nube independiente de tu computador.

`live.js` consulta periódicamente el backend —cada dos segundos mientras corresponde— y actualiza los indicadores. La animación de carga representa ese estado; no está ejecutando la IA en el navegador.

## 6. Los estados que conviene distinguir

| Estado o concepto | Qué significa |
|---|---|
| `reading` / `identifying` | Lectura del PDF / identificación de solicitudes |
| `needs_review` / `confirmed` | Identificación pendiente de revisión / confirmada |
| Candidato recuperado | Fragmento potencialmente útil, aún no prueba suficiente |
| Respaldo encontrado | Hay pasajes seleccionados; pueden quedar confirmaciones |
| Pendiente bloqueante | Debe resolverse para que la solicitud avance según las reglas |
| `error` de análisis | No se obtuvo una evaluación válida; no significa documento inexistente |
| `waiting_review` en preparación | Hay solicitudes sin redactar o errores que necesitan intervención |
| `ready` | Su significado depende del proceso: análisis terminado, preparación lista o respuesta lista para aprobar |
| `approved` | Aprobación humana registrada para una versión comprobada |
| `stale` | Cambiaron entradas relevantes y hay que actualizar el resultado |

Las huellas (`fingerprint`, `input_hash`) son identificadores calculados del contenido y sus dependencias. Impiden reutilizar una aprobación como si nada hubiera cambiado cuando se modifica la respuesta o el respaldo.

## 7. Qué ocurre si falla una solicitud

La ruta específica comienza en `static/recorrido/source-analysis-feedback.js` y `live.js`:

```text
«Reintentar las N solicitudes con error»
 → POST /api/cases/{id}/preparation {version, retry_failed_only: true}
 → source_service.py verifica vigencia y determina los IDs fallidos
 → conserva resultados correctos y procesa solo los fallidos
```

`source_passages.py` y `source_assessment.py` conservan diagnósticos como rango inválido, formato incompleto o error del proveedor. Si las fuentes o solicitudes cambiaron, no se puede prometer un reintento selectivo sobre las mismas entradas: se solicita actualizar. Consulta [CITAS_POR_UBICACION.md](CITAS_POR_UBICACION.md).

## 8. Cómo recorrer el código sin perderte

Haz estas cinco lecturas en orden. No necesitas leer cada instrucción del archivo:

1. **`app.py` → `create_app()`**: localiza qué servicios crea y qué dependencias entrega a cada uno.
2. **`static/recorrido/live.js` → `live-confirm`**: sigue el clic hasta `/confirm-and-prepare`.
3. **`preparation.py` → `run()`**: identifica las etapas `sources`, `points`, `drafts` y `review`.
4. **`workflow.py`, `source_graph.py`, `draft_graph.py`**: lee `add_node` y `add_edge` para ver el orden real.
5. **`live-document.js` → `save()` y `generate()`**: compara guardar, comprobar, aprobar y exportar.

Después usa este mapa para una duda concreta:

| Quiero entender o cambiar… | Empieza en… | Pruebas relacionadas |
|---|---|---|
| La separación de solicitudes y su origen | `identification.py`, `models.py` | `test_core.py`, `test_app.py` |
| Qué fuentes se recuperan | `source_retrieval.py`, `source_context.py` | `test_hybrid_retrieval.py`, `test_source_targeted_passages.py` |
| Una cita inválida | `source_passages.py`, `source_assessment.py` | `test_source_passages.py`, `test_source_analysis.py` |
| Cuándo comienza a redactar | `preparation.py`, `draft_service.py` | `test_predraft_preparation.py` |
| Un pendiente o una confirmación | `review_service.py`, `evidence_contract.py` | `test_document_decisions.py`, `test_review_service_api.py` |
| La actualización con IA | `response_proposals.py` | `test_response_proposals.py` |
| Guardado del documento completo | `office_workspace.py`, `live-document.js` | `test_office_workspace.py` |
| Word, PDF o membrete | `office_renderer.py`, `office_word.py`, `office_templates.py` | `test_office_renderer.py`, `test_office_templates.py` |
| Un reintento de errores | `source_service.py`, `preparation.py` | `test_failed_source_retry.py` |

## 9. Un ejercicio para comprobar que lo entendiste

Sin ejecutar cambios, busca estas expresiones en el editor:

```powershell
# Desde la carpeta pqrs-claro
rg -n 'live-confirm|confirm-and-prepare' src/pqrs_claro
rg -n 'def run|before_draft|ready_only' src/pqrs_claro/preparation.py
rg -n 'def _ready_for_draft' src/pqrs_claro/draft_service.py
rg -n 'async function save|async function check|async function generate' src/pqrs_claro/static/recorrido/live-document.js
```

Preguntas de control:

- ¿Quién conserva el PDF? `CaseStore`, en disco y SQLite; no el modelo.
- ¿Quién selecciona un pasaje? La IA propone una ubicación y Python materializa y valida el texto.
- ¿Quién decide si puede comenzar la redacción? Las reglas de elegibilidad del servicio, con los pendientes y decisiones guardadas.
- ¿Quién aprueba? La persona que realiza la acción explícita; la IA comprueba y propone.
- ¿Guardar cambia mi redacción? Guarda la edición y puede comprobarla; una nueva propuesta de IA pertenece a otro flujo.
- ¿Dónde se buscan documentos? En la biblioteca local habilitada; no automáticamente en OnBase.

## 10. Alcance de esta guía

Describe implementación inspeccionada, no una nueva ejecución de un expediente real. No se consultaron documentos privados ni se hicieron llamadas de IA para construirla. El proveedor implementado es OpenAI; `config.py` tiene `gpt-5.6-luna` como valor predeterminado, modificable por configuración. Cambiar el nombre por un modelo de otro proveedor no implementa por sí solo su integración.

El responsable de sesión es una atribución local de acciones, no autenticación institucional. El sistema local tampoco acredita por sí mismo expedición, firma ni entrega documental. Estas limitaciones importan para interpretar lo que muestra cada pantalla.
