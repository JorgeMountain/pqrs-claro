# Fase 4: fuentes y evidencia por solicitud

## Resultado esperado

Después de confirmar la identificación, seleccionar una solicitud y comprobar **qué fuentes pueden respaldarla, dónde está el fragmento pertinente y qué falta**. Esta fase prepara evidencia; la redacción y aprobación de respuestas siguen en las fases 5 y 6.

## Recorrido

1. **Incorporar documentos.** Cargar un PDF, DOCX o TXT con título, categoría y procedencia. Las fuentes pueden ser generales o estar vinculadas a un expediente; los soportes de un caso deben quedar en ese caso.
2. **Conservar y leer.** Guardar el original, su versión y huella SHA-256. Extraer texto con una ubicación rastreable. En PDF se conserva la página; el OCR requiere contraste con la imagen. DOCX y TXT se ubican por bloques o líneas del texto extraído, sin inventar páginas de Word.
3. **Revisar la fuente.** Registrar quién revisó el documento y su observación. La vigencia y la pertinencia para el caso requieren una decisión consciente; la fecha de carga no certifica ninguna de ellas.
4. **Buscar por solicitud.** Python recupera fragmentos del conjunto de fuentes disponible para ese expediente. Una coincidencia de palabras solo indica que merece revisión.
5. **Evaluar el respaldo.** La IA examina candidatos para esa solicitud, señala pertinencia, límites y faltantes. Python comprueba las referencias contra los fragmentos recuperados y aplica las restricciones de uso de las fuentes.
6. **Consultar y actualizar.** Mostrar resultados, fuentes y pendientes. Si cambia la biblioteca o la solicitud usada para la búsqueda, el resultado requiere actualización; se conserva la evaluación anterior para trazabilidad.

```mermaid
flowchart LR
    A[Identificación confirmada] --> B[Fuentes disponibles para el caso]
    B --> C[Recuperar fragmentos por solicitud]
    C --> D[Evaluar pertinencia y faltantes]
    D --> E[Guardar resultado y referencias]
    E --> F[Revisar respaldo en la pantalla]
```

## Categorías y uso

| Categoría | Puede aportar | Comprobación necesaria |
|---|---|---|
| Norma nacional | Reglas generales aplicables | Procedencia, vigencia y aplicación al caso |
| Norma institucional | Reglas de la institución | Autoridad de la fuente, versión, vigencia y ámbito |
| Evidencia del caso | Hechos de ese expediente | Identificación del caso, fecha de corte y responsable |
| Oficio anterior | Estructura y estilo de una comunicación | Sus hechos y afirmaciones no se trasladan al caso actual |
| Respuesta histórica | Contenido atribuido al trámite anterior o copia del propio oficio solicitado | Coincidencia de asunto, persona, periodo, versión y soportes; la identidad del archivo es preliminar |
| Petición histórica | Preguntas y manifestaciones del peticionario | No confundirlas con hechos corroborados ni respuestas |
| Anexo histórico | Evidencia del trámite anterior o archivo pertinente | Relación con la nueva solicitud, revisión y alcance temporal |

El [archivo histórico](HISTORICOS.md) incorpora colecciones con procedencias y relaciones propias. Se vinculan explícitamente a cada expediente antes de utilizarlas en la búsqueda.

Los documentos nuevos comienzan pendientes de revisión. La condición de revisado registra una declaración atribuida, no una verificación jurídica automática. Una norma cuya vigencia falta por verificar debe seguir mostrando esa limitación.

## Búsqueda inicial y papel de la IA

La recuperación inicial usa **BM25**, una búsqueda textual que ordena fragmentos según las palabras de la solicitud y su presencia en la biblioteca. Esa puntuación no es un porcentaje de certeza ni una conclusión sobre suficiencia.

La búsqueda combina dos recorridos dentro de las fuentes permitidas para el expediente: coincidencias generales y pasajes de contestaciones históricas detectados a partir de expresiones explícitas como «damos respuesta a su solicitud». El marcador es un indicio de estructura, no una prueba de que el contenido posterior resuelva la petición. También se consideran indicios del tipo y número del documento solicitado para dar prioridad al archivo sobre correos o preguntas que lo mencionan.

Se recuperan hasta **24 fragmentos candidatos**, con control de repeticiones, y la IA puede seleccionar hasta **8 fragmentos de respaldo**. Encontrar el documento correcto y encontrar dentro de él el pasaje pertinente son comprobaciones distintas. El original y su referencia permanecen disponibles para la persona.

En la llamada a la API, cada candidato recibe un alias cerrado `C1` a `C24`. La IA elige esos alias y Python los traduce a los identificadores originales mediante un mapa exacto; un alias desconocido se rechaza. Estos alias son un detalle interno de la evaluación. Las referencias guardadas mantienen la fuente, versión y ubicación originales, y la IA no puede reescribir sus citas.

El rol `document` admite una respuesta histórica cuando se pide copia de ese mismo oficio o respuesta y el fragmento permite identificarlo de forma preliminar. No acredita expedición, integridad ni entrega. Un correo puede tener ese rol si se solicita el correo; su existencia y la lista de adjuntos no localizan por sí solas cada archivo adjunto. Una petición histórica conserva el rol de antecedente sobre lo solicitado o manifestado.

La evaluación mantiene el periodo de los hechos consultados. Una petición nueva sobre 2015 debe contrastarse con los registros y antecedentes pertinentes de 2015. Revisar su aplicabilidad no supone exigir datos actuales o repetir comprobaciones ya documentadas sin una razón relacionada con la solicitud.

Esta versión no usa embeddings. Antes de añadir búsqueda por significado se debe medir qué fuentes relevantes omite la búsqueda textual y comparar la mejora en casos con una referencia humana. Si una búsqueda no encuentra un acta, el resultado es “no se encontró en las fuentes disponibles”; no prueba que el acta no exista.

## Un ejercicio con Aula Abierta

Todos los documentos de `examples/sources/` están marcados como ficticios. Las dos fuentes predeterminadas son las reglas de Aula Abierta y el registro del caso EJEMPLO-042. Se incorporan al ámbito del expediente de ejemplo para no mezclarse con una biblioteca real.

| Solicitud | Fuente esperada | Qué debe mostrar el sistema |
|---|---|---|
| P1. Procedimiento y requisitos | `norma_ficticia.txt` | Pasos del trámite y requisitos de la versión cargada |
| P2. Fecha de recepción y estado | `registro_ficticio.txt` | Recepción 2026-09-01 y estado “En revisión” al corte 2026-09-07 |
| P3. Copia completa del acta | No hay archivo del acta | Falta verificar su existencia y obtener la copia completa; el registro no la sustituye |

Los identificadores P1, P2 y P3 corresponden a la referencia del ejemplo; lo que se compara en una evaluación es el contenido de cada solicitud.

Hay dos documentos adicionales para pruebas específicas:

- `oficio_anterior_ficticio.txt`: menciona entrega de un acta en EJEMPLO-999. No puede respaldar una entrega en EJEMPLO-042 ni sustituir el acta.
- `norma_ficticia_v2.txt`: agrega un requisito. Debe incorporarse como nueva versión de la misma fuente para comprobar que se conserva la anterior y los resultados necesitan actualizarse.

`manifest.json` describe las categorías y los usos `default`, `style_test` y `version_test`. El responsable y la revisión de estas fuentes también son ficticios; esos valores no deben copiarse a documentos reales.

## Estado, persistencia y alcance

El grafo de fuentes trabaja después de la confirmación de solicitudes. Conserva una fotografía de las solicitudes y de la biblioteca utilizada, además del avance por solicitud. Un fallo debe permitir consultar el trabajo ya guardado y continuar desde el avance persistido.

Actualizar la búsqueda no reabre la identificación confirmada ni aprueba una respuesta. Los resultados desactualizados se distinguen de los vigentes. Las versiones anteriores permiten consultar lo que el sistema había evaluado sin presentarlo como el estado actual.

## Validación documental reproducible

El script `scripts/validate_history.py` compara el grafo real de fuentes con una referencia documental preparada antes de llamar al modelo. La referencia contiene solicitudes con citas literales de origen, grupos de fuentes esenciales equivalentes, límites esperados y afirmaciones prohibidas. Las evidencias usadas para fijar esa referencia se comprueban al preparar la muestra y no se incorporan como respuestas esperadas al contexto de la IA.

Desde la raíz del proyecto:

```powershell
.\scripts\dev-python.ps1 scripts/validate_history.py prepare --reference output/validation-f4/reference-proposal.json
.\scripts\dev-python.ps1 scripts/validate_history.py run --subset development
.\scripts\dev-python.ps1 scripts/validate_history.py run --subset holdout
.\scripts\dev-python.ps1 scripts/validate_history.py report
```

`prepare` congela la referencia y prepara expedientes QA en una copia coherente de SQLite, limitada a las colecciones declaradas. Copia los PDF de las peticiones que integran la muestra. Si el origen es una pregunta reproducida en DOCX, genera un PDF de trabajo marcado como derivado y conserva aparte la cita literal en la fuente real. Los originales de la biblioteca se consultan por lectura y comprobación de SHA, sin copiar todo el archivo histórico ni modificar los expedientes de trabajo.

`run` utiliza `SourceService`, LangGraph y el evaluador OpenAI de la aplicación. `development` ejecuta las solicitudes de desarrollo y `holdout` las reservadas según la referencia. Esta prueba comienza con solicitudes preparadas documentalmente; no prueba la identificación automática de la petición ni constituye confirmación institucional de su contenido.

Cada invocación conserva un directorio único `attempts/<id>/`. Su archivo `execution.json` registra hora, modelo, versión de análisis, Python, dependencias, commit de Git y hashes del código. Antes de cada muestra archiva las llamadas y resultados existentes; después conserva los nuevos. Los errores de ejecución o comprobación se registran por muestra sin convertirlos en resultados aprobados, y el lote puede continuar con las restantes.

Las comprobaciones separan la recuperación de fuentes esenciales, la literalidad y versión de las citas, y la persistencia de resultados. Antes de buscar se comprueban los SHA de los originales elegibles. Al revisar la persistencia se verifica también el PDF QA y que desvincular la colección marque el resultado desactualizado; restaurar los mismos vínculos permite contrastar su huella de entradas. La comparación literal usa el texto extraído conservado, por lo que no sustituye una nueva extracción o revisión visual del original.

Los resultados correctos pueden reutilizarse desde el avance guardado; el informe distingue si el intento llamó al modelo. Para repetir la inferencia tras cambiar el motor se debe actualizar su versión de análisis o preparar otra carpeta con `--output-dir output/validation-f4/repeticion-01`. Conservar entradas y configuración no garantiza que una nueva llamada al modelo produzca texto idéntico.

`report` genera `technical-summary.json` y `TECHNICAL-REPORT.md`. Estos artefactos mantienen separadas las comprobaciones técnicas y la revisión semántica e institucional. No encontrar una fuente esencial existente y legible es un fallo de recuperación, aunque el sistema advierta que falta información. La decisión de aceptación requiere además revisar pertinencia, alcance, periodos y faltantes con la referencia y el responsable correspondiente.

## Criterios de aceptación

1. Recuperar procedimiento y requisitos para P1 y los dos datos del registro para P2.
2. Mantener pendiente la copia del acta de P3.
3. Mostrar referencias que correspondan al texto conservado y al original correcto.
4. Conservar el ámbito de cada expediente y el uso de cada categoría.
5. Distinguir documentos revisados de documentos por revisar y reflejar la vigencia sin inferirla.
6. Conservar versiones y señalar los resultados que requieren actualización.
7. Guardar resultados parciales y mostrar fallos del proveedor como fallos, sin completar con datos simulados.
8. Permitir comprender los soportes y pendientes desde cada solicitud.

Estos son criterios de aceptación, no un registro de pruebas ejecutadas. La evidencia y las limitaciones de las verificaciones realizadas se registran en [VALIDACION.md](VALIDACION.md).

Para la decisión sobre alojamiento y futuras conexiones, consultar [ALMACENAMIENTO.md](ALMACENAMIENTO.md).
