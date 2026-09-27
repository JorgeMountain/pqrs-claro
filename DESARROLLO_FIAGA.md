# Copia aislada para la revisión inicial FIAGA

Creada desde el commit 55ed94a2ce4df50879c68c8f7040949452127537, verificado en origin/master el 21 de septiembre de 2026.

- Rama: codex/fiaga-revision-inicial.
- Código: C:/Users/jorge/Desktop/AgenteO/pqrs-claro-fiaga.
- Datos propios: data/ dentro de esta copia. Se inicia sin expedientes ni conexión Gmail copiados.
- Dependencias: .runtime/ propia, copiada de la versión de presentación.
- Acceso de desarrollo: http://127.0.0.1:8773/.
- Vista actual de fases 2 a 4: http://127.0.0.1:8774/, con `scripts/start-fiaga-preview.ps1`.
  Conserva datos separados en `output/qa/fiaga-phase2/data`. El proceso anterior en 8773
  no se reinició: la revisión automática rechazó detenerlo. No se comparte la base de datos.
- Presentación: C:/Users/jorge/Desktop/AgenteO/pqrs-claro, http://127.0.0.1:8772/.

Usar `scripts/start-fiaga.ps1` para el desarrollo habitual o `scripts/start-fiaga-preview.ps1` para la vista actual de fase 2 con datos independientes. Ambos fijan datos y puerto y comprueban que importan el código de esta carpeta. Los scripts de arranque heredados siguen conservados; no usarlos para FIAGA.

La configuración de IA puede leer la clave compartida ya existente; no se ha duplicado ni mostrado. Este aislamiento separa código, archivos, bases de datos y dependencias; no crea una cuenta independiente del proveedor. Arrancar y comprobar páginas no ejecuta por sí solo el análisis de una petición.

## Respaldo de presentación

C:/Users/jorge/Desktop/AgenteO/output/respaldo-presentacion-20260921-182855 contiene el código en ZIP, data/, temporales locales e inventario de archivos. Las bases SQLite se respaldan con la API de SQLite y se comprueban con integrity_check. Es un respaldo local con datos institucionales y configuración de conexiones: no publicarlo en Git.

## Revisión inicial implementada

La especificación y los seis adjuntos se conservan en ../Documentos/FIAGA_revision_inicial_2026-09-17/. El análisis y la decisión humana previos a preparar respuestas están integrados en «Procesar solicitud», dentro de «Resumen del trámite». La fase 1 de simplificación elimina la pantalla independiente y conserva los hallazgos, soportes y controles existentes.

La primera versión de la revisión inicial está implementada en esta copia. Consulta
[alcance, uso y límites](docs/REVISION_INICIAL_FIAGA.md). La rama no se ha fusionado ni publicado.

La biblioteca de desarrollo contiene cuatro documentos institucionales del correo FIAGA y un
expediente ficticio de comprobación con IA real. Los expedientes de presentación siguen separados.

La fase 2 analiza datos y lenguaje una vez por documento y muestra el tipo editable en cada tarjeta.
Competencia, dependencia y traslado quedaron aplazados. Los análisis previos se conservan en el
historial y requieren una actualización explícita para usar el nuevo alcance.

La fase 3 reúne la revisión en una casilla conjunta y la acción «Confirmar y preparar respuestas».
Solo exige explicaciones particulares ante observaciones o cambios de criterio. Guarda primero;
si hay rutas alternativas no prepara, y si falla la preparación permite reintentar sin duplicar
la decisión. Se mantiene en la misma instancia de 8774, sin cambios del backend ni reinicios.

La fase 4 validó el recorrido completo: 1.208 pruebas generales, 4 nuevas de integración FIAGA
y 13 de confirmación aprobadas; una prueba semántica omitida por faltar su modelo local.
Se ajustó la interfaz del oficio para deshabilitar la generación mientras existan pendientes
o cambios sin guardar. Evidencia y límites: `docs/REVISION_INICIAL_FIAGA.md`, sección fase 4.

## Clasificación JEV por Vercel (23 de septiembre de 2026)

Los dos lanzadores FIAGA activan JEV para sugerir el tipo de cada petición confirmada.
Usan la clave `AI_GATEWAY_API_KEY` del entorno o de `.env.jev.local`, excluido de Git.
OpenAI conserva las demás comprobaciones y la redacción. Los análisis anteriores requieren
actualización explícita y se mantiene la confirmación humana antes de preparar respuestas.

La integración se comprobó con una llamada real y un PDF ficticio en 8774. Resultado y
alcance: `docs/REVISION_INICIAL_FIAGA.md`, sección «Clasificación JEV». La instancia 8774
se reinició con este código; 8773 no estaba en ejecución durante esta comprobación.
