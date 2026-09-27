# Revisión del trámite FIAGA: fases 1 a 4

## Uso

La vista actual, incluidas las fases 2 a 4, está en http://127.0.0.1:8774/ y se inicia con
`scripts/start-fiaga-preview.ps1`. Usa una copia de datos en `output/qa/fiaga-phase2/data`.
La revisión automática rechazó detener/reiniciar el proceso anterior en 8773, sin aportar una
razón específica; se conservó ese proceso y se inició esta instancia independiente.
El arranque habitual `scripts/start-fiaga.ps1` cargará el código nuevo cuando se reinicie
manualmente el proceso anterior. La carpeta de presentación en `../pqrs-claro` no se modifica.

1. Cargar una petición y revisar las tarjetas en «Procesar solicitud», junto al documento original.
2. Confirmar las solicitudes. En el «Resumen del trámite», pulsar «Analizar trámite».
3. Abrir «Ver detalle y decisión general» para revisar datos y lenguaje una sola vez.
4. Corregir el tipo en cada tarjeta. Su desplegable contiene el fundamento y la decisión de esa petición.
5. Indicar el responsable y marcar una sola confirmación del resumen y de todas las peticiones.
   «Confirmar y preparar respuestas» guarda y comienza la preparación. Una ruta alternativa cambia
   esa acción a «Guardar decisión» y conserva el expediente en este paso.

Ninguna de estas acciones envía comunicaciones. Los borradores sugeridos son editables cuando
existe respaldo suficiente y el texto editado queda guardado con la decisión.

## Fase 1 de simplificación de la interfaz

Implementada el 21 de septiembre de 2026 exclusivamente en esta copia de desarrollo.
El recorrido vuelve a tener tres etapas: Procesar solicitud, Preparar las respuestas y Revisar el oficio.
El resumen aparece entre el título y las tarjetas; sus detalles y decisiones se despliegan en la misma
pantalla. El PDF, el resaltado de pasajes y los ajustes del ancho de las columnas siguen disponibles.
Los enlaces antiguos con step=4 abren ahora step=1, sin una pantalla adicional.

En ese primer hito se conservaron el análisis existente, las decisiones guardadas y los controles
del servidor. El resumen contaba las peticiones con observaciones o verificaciones pendientes,
sin reinterpretarlas como un análisis general. La fase 2 descrita abajo sustituye ese alcance.

Se comprobaron en navegador el guardado, la persistencia al recargar, el bloqueo de avance con
una ruta alternativa, el retorno a las respuestas y el original sin perder una edición local del
trámite. El caso utilizado es ficticio. Los desplegables funcionan por teclado y no se detectó
desbordamiento horizontal a 320, 768, 1024 y 1440 píxeles, ni errores/avisos en consola.
Pasaron cuatro pruebas de rutas, siete comprobaciones de renderizado de estados y la revisión
sintáctica de los módulos JavaScript modificados. No se repitió la batería completa de backend.
El punto de retorno anterior está en output/checkpoints/antes-fase1-20260921-221936/.

## Fase 2: análisis general y clasificación en las tarjetas

Implementada el 21 de septiembre de 2026. El contrato de análisis pasa a la versión 2:
datos y lenguaje pertenecen al documento completo; clasificación y antecedentes, a cada petición.
Los informes anteriores permanecen en el historial y requieren «Actualizar análisis» antes
de registrar decisiones con el nuevo alcance. No se convierten silenciosamente sus resultados.

El punto de retorno anterior está en `output/checkpoints/antes-fase2-20260921-223449/`.
En este segundo hito se mantenían acciones separadas para guardar decisiones y preparar respuestas.
La fase 3, descrita abajo, las reúne.

### Alcance implementado

- Datos/requisitos y lenguaje se analizan una sola vez sobre el documento completo.
- Clasificación por petición, editable en cada tarjeta; los fundamentos quedan desplegables.
- Competencia, dependencia y traslado están fuera del contrato de IA y de las decisiones de esta fase.
- Antecedentes por petición solo cuando existen respuestas anteriores recuperadas. Sin histórico,
  se marca la consulta no disponible una sola vez, sin inventar ausencia ni generar un faltante.
- Análisis con IA real usando texto original y fragmentos de la biblioteca local. Sin clave o ante
  fallo de proveedor se informa el error; no se sustituye por resultados simulados.
- Selecciones de páginas/líneas validadas contra el original. Las citas de fuentes se materializan
  desde identificadores existentes, con texto, documento, ubicación y advertencias de lectura.
- Recuperación acotada de antecedentes: solamente colecciones vinculadas al expediente. No se
  interpreta una búsqueda sin coincidencias como inexistencia de antecedentes.
- Alertas de tratamiento especial, con datos extraídos y término escrito contrastado con el original.
- Propuestas generales de complemento, rechazo o revisión especializada; por petición,
  continuación, respuesta reiterativa sustentada o revisión especializada.
  Sin respaldo necesario no se genera el borrador y se muestran los insumos pendientes.
- Decisiones humanas versionadas y persistentes; corrección de clasificación y rutas,
  justificación y responsable registrado. El nombre introducido no acredita identidad autenticada.
- Bloqueo del inicio de preparación, redacción, aprobación de respuestas y generación del oficio
  mientras no exista una decisión general vigente de continuar y todas las peticiones permitan avanzar.
- Cambiar solicitudes o fuentes invalida la decisión inicial. Reanalizar retira su autorización.
  Una decisión inicial posterior modifica la huella de los borradores y revisiones derivados.
- Recuperación de análisis interrumpidos y protección contra sobrescritura desde otra pestaña.
- Historial persistente; los datos se eliminan con el expediente solo mediante la operación
  explícita existente de eliminación definitiva.

## Fase 3: confirmación conjunta

Implementada el 21 de septiembre de 2026 en la misma copia de desarrollo. Punto de retorno:
`output/checkpoints/antes-fase3-20260921-230417/`, con código previo y respaldo SQLite comprobado.
Esta fase modifica la interfaz y su coordinación de llamadas; conserva el contrato y los controles
del servidor de fase 2. No requiere reiniciarlo y usa los mismos datos independientes en 8774.

- Una casilla de revisión conjunta y un responsable al final de la pantalla sustituyen las casillas
  por documento y por petición. Cambiar tipo, ruta, texto o responsable retira esa confirmación local.
- Las observaciones son opcionales cuando se acepta una propuesta sin alertas. Se registra
  «Confirmación conjunta: se acepta la propuesta de análisis mostrada», sin inventar comprobaciones.
- La interfaz exige explicación ante observaciones, verificaciones pendientes, tratamiento especial,
  cambios de clasificación o rutas alternativas, incluso al apartarse de una alternativa sugerida.
  El histórico no disponible sigue sin generar un requisito de explicación por sí solo.
- «Confirmar y preparar respuestas» guarda primero la decisión vigente. Solo inicia la preparación
  si el servidor devuelve autorización. No es una transacción única: si falla la preparación,
  la decisión permanece guardada y se muestra el error con opción de reintentar, sin duplicarla.
- Las rutas alternativas se guardan sin preparar respuestas. La acción muestra «Decisión guardada»
  y permanece deshabilitada hasta que se edite algo. Un guardado fallido conserva las ediciones locales.
- Los campos de ruta, observaciones y comunicaciones siguen en los detalles. El original, los tipos
  editables en tarjetas y el historial permanecen disponibles. Las versiones previas no se reescriben.

La fase 4 de comprobación del recorrido se completó después de este hito; sus resultados están
documentados al final junto a las validaciones específicas de las fases anteriores.

## Fuentes y límites

Los seis adjuntos originales siguen conservados en ../Documentos/FIAGA_revision_inicial_2026-09-17/
respecto de la carpeta raíz de esta copia. Se incorporaron a su biblioteca de desarrollo el manual,
la guía de mejoramiento, el protocolo y la Resolución 37421. La procedencia señala el correo del
17 de septiembre; la incorporación no aprueba la vigencia ni autenticidad de cada documento.
El DOCX de requerimientos y el diagrama definen el diseño y se conservan como insumos.

Esta versión permite decidir rutas distintas por solicitud, pero retiene el expediente completo
si alguna requiere otra actuación. La preparación parcial por rutas y el trámite institucional
de complementos, traslados y respuestas reiterativas requieren una etapa posterior.

La búsqueda de posibles reiteraciones depende del histórico y fuentes que se incorporen.
La asignación y la competencia quedaron aplazadas. La pertinencia de las recomendaciones queda sujeta a
revisión institucional. No hay acceso nuevo a sistemas institucionales, radicación, asignación
efectiva ni envío automático. La revisión jurídica posterior durante la gestión sigue separada.

Los días conservados en el registro son referencias del requerimiento FIAGA por tipo y su mínimo,
no vencimientos; no se muestran como plazos operativos. No se calcula calendario de días hábiles, suspensiones,
ampliaciones ni prioridad sobre términos especiales. Esas reglas necesitan validación posterior.

## Componentes

- `intake_models.py`: contrato de análisis y decisiones.
- `intake_engine.py`: instrucciones, análisis estructurado y validación de referencias.
- `intake_service.py`: recuperación, persistencia, versiones, decisiones y API.
- `initial-review.js` y `initial-review.css`: vista integrada al recorrido.
- `initial-confirmation.js`: reglas de confirmación conjunta y secuencia de guardado/preparación.
- `preparation.py`, `draft_service.py` y `review_service.py`: controles de avance y vigencia.

La activación es explícita con `Settings.initial_review_enabled=True` en `run-fiaga.py`.
Los demás arranques conservan su comportamiento previo por defecto. No se ha fusionado esta
rama ni modificado la carpeta original de presentación.

## Validación de fase 2

Pasaron 115 pruebas de revisión inicial, preparación, preparación previa a redacción, redacción,
revisión humana y rutas del espacio de trabajo. Se comprueban el alcance general frente al
individual, los informes anteriores, las decisiones vigentes, las referencias, las rutas alternativas
y la ausencia de histórico. Las pruebas automáticas usan dobles del proveedor y carpetas temporales.
Ruff y la revisión sintáctica de los módulos JavaScript modificados también pasaron.

La comprobación con IA real se hizo desde el navegador en 8774, sobre la copia independiente
del caso ficticio `094b2c884b84413f81baabae0d947ad7`. Devolvió dos comprobaciones generales,
una petición de documentos y una de información. La crítica fuerte no generó una alerta de
irrespetuosidad. Sin respuestas históricas disponibles, la consulta de antecedentes quedó no
disponible, sin bloquear por sí sola la continuación. El resultado está en
`output/qa/fiaga-phase2/resultado.json`.

La verificación en navegador comprobó el guardado de la decisión general y de los tipos editados
en las tarjetas, persistencia al recargar, bloqueo por ruta alternativa y por cambios sin guardar,
y habilitación de la preparación tras guardar la continuación. Las decisiones del ejemplo llevan
el responsable «QA automática · fase 2 · caso ficticio»; no son aprobaciones institucionales.
El historial muestra la decisión general y el tipo elegido por petición, conservando también las
versiones anteriores. No hubo desbordamiento horizontal a 320, 768, 1024 y 1440 píxeles con
formularios desplegados, ni avisos o errores en la consola del navegador.

`scripts/check_initial_review_live.py` queda actualizado al contrato de fase 2. Importa una nueva
petición ficticia y consume el servicio de IA exclusivamente en 8773; no se volvió a ejecutar en
esta fase porque ese proceso sigue cargando el backend anterior. Debe reiniciarse manualmente
antes de usar el script. La evidencia histórica de la primera implementación permanece en
`output/qa/initial-review-live/`.

## Validación de fase 3

Pasaron 13 pruebas de JavaScript (`node --test tests/test_initial_confirmation.mjs`) y 34 pruebas
de servidor (`tests/test_initial_review.py` y `tests/test_workspace_routes.py`). Cubren confirmación
explícita, explicación de excepciones, bloqueo de tipos sin determinar, orden de guardado y preparación,
fallos, reintentos y los controles de vigencia existentes. El fallo de preparación se verificó con
dobles de prueba; no se provocó una caída del servidor real.

En el caso ficticio de 8774 se comprobó la casilla única, la validación de una explicación vacía,
el guardado de una ruta de complemento y su bloqueo de avance. Después, una única acción guardó la
confirmación conjunta y abrió las respuestas: la preparación registró la misma revisión 15 y quedó
esperando los puntos de revisión propios de la etapa 2. No se aprobaron esos puntos ni se enviaron
comunicaciones. La evidencia JSON está en `output/qa/fiaga-phase3/`.
La confirmación y las observaciones vacías se conservaron al consultar el original. Se verificó
persistencia al recargar, foco de teclado en la casilla única y ausencia de desbordamiento horizontal
a 320, 768, 1024 y 1440 píxeles. La consola del navegador quedó sin avisos ni errores.

## Fase 4: validación del recorrido completo

Completada el 21 de septiembre de 2026. Punto de retorno:
`output/checkpoints/antes-fase4-20260921-231953/`. Se conservó un respaldo SQLite comprobado y
los archivos anteriores al ajuste. La carpeta original `../pqrs-claro` permanece sin modificaciones
de esta fase; solo conserva su directorio `tmp/` preexistente sin seguimiento.

### Resultados

- Batería general: **1.208 aprobadas, 1 omitida**, sin fallos. La omitida necesita un modelo
  semántico local no instalado; no se descargó durante la prueba. Se mantiene un aviso de
  deprecación de `anyio` en `starlette.testclient`, sin efecto sobre los resultados.
- Recorrido FIAGA completo: **4 pruebas nuevas aprobadas** en `tests/test_fiaga_flow.py`.
- Confirmación conjunta: **13 pruebas JavaScript aprobadas**. Total: **1.225 aprobadas**.
- Ruff del nuevo archivo, sintaxis JavaScript y `git diff --check` correctos.

Las cuatro pruebas nuevas recorren carga de PDF ficticio, identificación, confirmación, pausa FIAGA,
análisis general, decisión, preparación de dos respuestas, comprobación, aprobación, vista del oficio
y descarga de DOCX, PDF y ZIP. Usan API, SQLite, versionado y archivos reales; identificación, IA y
conversión final son dobles explícitos. Verifican el flujo de software, no la calidad jurídica de la IA
ni la fidelidad de una conversión real de Word en esta fase.

| Escenario | Resultado comprobado |
| --- | --- |
| Sin revisión inicial vigente | Preparación y exportación bloqueadas. |
| Continuación confirmada y respuestas comprobadas | Preparación ligada a la revisión vigente y archivos de prueba descargables. |
| Cambio de ruta general a complemento | Se retira el permiso para avanzar y se bloquean las descargas anteriores. |
| Cambio de clasificación | La decisión puede permitir continuar, pero las respuestas y archivos previos requieren actualizarse. |
| Cambio de fuente | El análisis queda desactualizado y se bloquean las descargas anteriores. |
| Edición de respuesta | Se invalida la aprobación y se bloquea la exportación anterior. |
| Historial anterior | Conservado sin sobrescritura después de las modificaciones. |

### Ajuste de interfaz y navegador

Se encontró que «Generar Word» y «Generar PDF» estaban activos aunque faltaban respuestas;
el servidor ya rechazaba generar, pero la interfaz invitaba a una acción imposible. Ahora ambos
botones quedan deshabilitados mientras haya respuestas pendientes, comprobaciones en curso,
resultados desactualizados o cambios sin guardar. Un oficio sin respuestas muestra ese estado y
el acceso de regreso, en lugar de anunciar comprobaciones superadas.

En el caso ficticio de 8774 se comprobaron el recorrido por las tres etapas, los motivos concretos
de los pendientes, el panel de fuentes con pasaje y enlace al original, el bloqueo visible de los
dos botones y el regreso a las respuestas. La vista del oficio no desborda horizontalmente a
320, 768, 1024 o 1440 píxeles; la consola quedó sin avisos ni errores.

El caso conserva sus puntos pendientes: no se dieron por comprobados para forzar una generación
en el servidor de desarrollo. No se enviaron comunicaciones ni se fusionó o publicó la rama.
Los resultados JUnit y el resumen de evidencias están en `output/qa/fiaga-phase4/`.

## Clasificación JEV

Integrada el 23 de septiembre de 2026 en los dos lanzadores FIAGA. La opción
`initial_classification_provider="jev"` activa `typesafe-ai/jev` mediante la ruta TypeSafe
de Vercel AI Gateway. El valor predeterminado de otros lanzadores sigue siendo `openai`.

JEV recibe el título, la descripción y los fragmentos originales de cada petición confirmada.
Los fragmentos se recuperan de las páginas originales, sin confiar en una cita guardada
que pudiera estar desactualizada. Las consultas se dividen por tamaño; un elemento demasiado
grande falla explícitamente, sin cortar su texto. La clave se lee únicamente en el servidor
desde `AI_GATEWAY_API_KEY` o `.env.jev.local`, que está excluido de Git.

OpenAI conserva requisitos generales, lenguaje, antecedentes, tratamiento especial y textos
explicativos. Su esquema de contexto ya no contiene el tipo de petición ni la comprobación
de clasificación: JEV aporta esos campos. Las referencias de OpenAI se restringen a los
identificadores de las fuentes suministradas; si no hay fuentes, la lista debe quedar vacía.

La interfaz identifica la sugerencia de JEV y muestra su confianza como una estimación,
con tipo editable y confirmación humana obligatoria. No se cambia de proveedor silenciosamente
si JEV falla. Se validan las respuestas y no se muestran cuerpos de error externos.
Un cambio de proveedor o de instrucciones invalida la vigencia del análisis anterior;
el historial se conserva y requiere actualización explícita.

### Comprobaciones

- Pasaron 56 pruebas de integración JEV, revisión inicial, flujo FIAGA y laboratorios,
  más 4 de rutas del espacio de trabajo y las 13 de confirmación JavaScript.
- Tras restringir las referencias de contexto, pasaron las 9 pruebas de `test_jev_intake.py`,
  incluida la nueva regresión del esquema de fuentes. Ruff y sintaxis JavaScript correctos.
- La llamada real en 8774 con el PDF ficticio `PRUEBA-FICTICIA-JEV.pdf` produjo
  `P1: information` para fechas/requisitos de admisión y `P2: documents` para copia del reglamento.
  Expediente: `ea369a3879d74b2bb4bf05b12035ad2f`.
- El navegador confirmó ambas sugerencias, el tipo editable, el detalle de JEV y la casilla
  de revisión sin marcar. El informe quedó `needs_review` y `can_prepare: false`.

Evidencia local: `output/qa/jev-intake/case.json` y `output/qa/jev-intake/result.json`.
La primera ejecución detectó una referencia inexistente en el resultado de OpenAI y se detuvo;
se corrigió el esquema y la repetición final completó el análisis. No se aprobaron decisiones
ni se reprocesaron expedientes reales. Esta muestra verifica la integración, no la precisión
general del modelo sobre todas las clases de peticiones.

## Análisis automático y paralelo — 24 de septiembre de 2026

La identificación dispara automáticamente la revisión del trámite. Una vez disponibles las
peticiones, JEV clasifica sus tipos al mismo tiempo que OpenAI analiza el documento y los
antecedentes disponibles. La pantalla muestra el progreso y luego el resumen y los tipos,
sin exigir confirmar la identificación antes de analizarlos. La confirmación conjunta final
valida también la identificación; solo entonces se puede iniciar la preparación de respuestas.

La clasificación usa hasta dos llamadas simultáneas, con dos peticiones por llamada. En pruebas
reales algunas parejas devolvieron HTTP 503 aunque sus peticiones individuales funcionaron:
solo esa pareja se divide en llamadas individuales, con el mismo modelo y texto completo.
Los errores persistentes dejan el análisis en error y permiten reintentar; nunca se suple JEV
con clasificaciones de OpenAI ni se aprueba un resultado parcial.

Al corregir una petición se vuelve a analizar el contenido actualizado. Las ediciones esperan
si hay un análisis activo. La huella compara contenido y fuentes, no el incremento de versión
administrativo de la confirmación. Un cambio de fuentes sigue invalidando el resultado.
Las referencias del análisis general reciben líneas numeradas y un esquema limitado a las
páginas y rangos existentes; las citas se comprueban contra el original antes de guardar.

Validación: pruebas de arranque automático, confirmación única, bloqueo antes de revisión,
corrección y reanálisis, cambios de fuentes, concurrencia con barreras, división de errores 503,
referencias acotadas, compatibilidad del flujo anterior y 18 pruebas JavaScript. También se
comprobó en navegador la transición de progreso a diez tipos sugeridos, sin errores de consola.
La prueba con IA real conserva `needs_review`, `confirmed_at=null` y `can_prepare=false`.

Vista independiente: `http://127.0.0.1:8776/`, iniciada mediante
`scripts/dev-python.ps1 scripts/run-fiaga-analysis-preview.py`, con datos en
`output/qa/fiaga-auto-analysis/data`. El servidor previo de 8774 no fue reiniciado: el indicador
`automatic_initial_review` permite que su interfaz conserve el flujo anterior mientras siga
usando el backend viejo. Evidencia de las pruebas en `output/qa/fiaga-auto-analysis/`.

Resultados reales guardados en `verification.json`: los expedientes ficticios
`1fad5ff4f7d0476393929bba5b245484` y `ff9d907beef94bad85997e9c6e020ce4` terminaron con diez
tipos `information` de JEV y confirmación humana pendiente. La segunda carga arrancó la revisión
automáticamente, pero necesitó un reintento por otro HTTP 503 del proveedor. Por tanto, se
validó el disparo automático y la recuperación, no una disponibilidad ininterrumpida de JEV.

## Atribución de expresiones ofensivas (27 de septiembre de 2026)

En esta copia FIAGA, OpenAI revisa el lenguaje y JEV conserva la clasificación del tipo.
La revisión de respeto distingue expresiones propias del solicitante de citas o relatos
sobre terceros, incluso sin comillas. Una cita aislada no genera por sí sola una alerta
contra el solicitante ni una ruta alternativa por lenguaje. El hecho relatado no se da
por probado. Los insultos propios en mensajes mixtos se siguen evaluando y la atribución
ambigua queda por verificar, con revisión humana.

Las instrucciones forman parte de la huella de vigencia: los informes anteriores se
conservan y necesitan actualización explícita. No se reprocesaron expedientes ni se
modificó la carpeta de presentación `../pqrs-claro`. La interfaz identifica la revisión
como «Lenguaje y atribución al solicitante». Pasaron 47 pruebas de revisión inicial e
integración JEV, Ruff y sintaxis JavaScript. La vista de análisis automático se inicia
con `scripts/run-fiaga-analysis-preview.py` en 8776 y datos de QA separados.

La comprobación real adicional con OpenAI devolvió JSON incompleto y no produjo un
informe aceptado. La validación contextual con ese proveedor queda pendiente; las
pruebas reales previas del laboratorio fueron con JEV y no se extrapolan a OpenAI.
El motor ahora transforma este error de formato en un aviso controlado de reintento.
