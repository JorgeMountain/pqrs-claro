# Gestión de Peticiones

Asistente PQRS en LangGraph: **comprender una petición, localizar sus soportes y preparar, revisar, aprobar y documentar respuestas trazables por solicitud**.

## Empezar

**Integración en un puerto activa:** `scripts/start.ps1`, `scripts/start-recorrido.ps1`
y `scripts/start-unificado.ps1` sirven el recorrido y la API en 8772, sin depender
de 8770. [Alcance, pruebas y activación](docs/INTEGRACION_UN_PUERTO.md).
El flujo aislado con IA real y Word/PDF pasó; Gmail se comprobó con transporte
simulado. [Evidencias y límites de fase 2](docs/QA_UNIFICACION_FASE2_20260919.md).

**Recorrido elegido para continuar el trabajo: http://127.0.0.1:8772.** Conservamos su diseño e interacción. Para iniciarlo o comprobar que sigue disponible, ejecuta `scripts/start-recorrido.ps1`. La biblioteca consulta documentos reales. «Cargar petición» y «Mis expedientes» permiten identificar solicitudes y, al confirmarlas, buscar fuentes y preparar respuestas automáticamente. Las respuestas reales ya se pueden editar y guardar desde sus tarjetas. «Actualizar con IA» propone ajustes basados en las decisiones registradas y permite comparar antes de aplicar o descartar. La demo original se conserva aparte; la revisión, aprobación por respuesta y generación de Word/PDF de expedientes reales están conectadas en «Revisar el oficio». [Preparación automática](docs/PREPARACION_AUTOMATICA.md). [Alcance de la biblioteca integrada](docs/BIBLIOTECA_RECORRIDO.md). La integración de 8770 se conserva como alternativa, no como sustituto aceptado.

Para iniciar el sistema con tus expedientes:

```powershell
cd C:\Users\jorge\Desktop\AgenteO\pqrs-claro
.\scripts\start.ps1
```

Abrir **http://127.0.0.1:8772**. Puedes cargar un PDF o importar una petición desde Gmail. Selecciona cada solicitud para contrastarla con el original; corrige lo necesario, guarda y confirma la identificación.

Las tres etapas son **Entender la petición → Preparar las respuestas → Revisar el oficio**. La interfaz anterior se conserva en **http://127.0.0.1:8772/anterior**. Ambas utilizan los mismos datos; la anterior no es una copia aislada. Consulta [el historial de interfaces](docs/INTERFAZ_PRINCIPAL.md).

## Qué incluye esta entrega

**Mis expedientes** incluye búsqueda, filtros, ordenación, paginación y una papelera
con confirmación y restauración. Conserva los documentos y las respuestas; no borra
fuentes compartidas. [Uso y alcance](docs/EXPEDIENTES.md).

- Parte 1: [objetivo, alcance y criterios de aceptación](docs/PLAN.md), con seis PDFs ficticios y referencia humana en [examples/cases.json](examples/cases.json).
- Parte 2: aplicación independiente, contratos de datos, SQLite para expedientes y checkpoints persistentes de LangGraph.
- Parte 3: carga y conservación del PDF original, extracción por página, OCR cuando hace falta, identificación estructurada, referencias literales, corrección y confirmación humana.
- Parte 4: [biblioteca local y búsqueda por solicitud](docs/FASE4.md), con fuentes PDF/DOCX/TXT, originales versionados, procedencia, revisión y vigencia, referencias a fragmentos y faltantes explícitos.
- Parte 5: [plan, redacción y comprobaciones](docs/FASE5.md), con borradores por solicitud, citas por párrafo, pendientes visibles y recuperación del avance.
- Parte 6: [revisión humana y aprobación](docs/FASE6.md), con edición, aportes escritos atribuidos, resolución de pendientes, reevaluación y aprobación de una versión concreta.
- Parte 7: [oficio en Word y PDF](docs/FASE7.md), con datos de salida, vista previa, anexos seleccionados, comprobación de fidelidad e historial de generaciones.

**Confirmar identificación** cierra el primer hito. **Preparar las respuestas** busca las fuentes disponibles, prepara los borradores iniciales y abre su revisión. Si ya existen respuestas revisadas, actualiza el respaldo conservando esos textos. **Revisar respuesta** permite editar, resolver pendientes, comprobar y aprobar. **Revisar el oficio** prepara Word, PDF y anexos desde las versiones aprobadas. La aprobación local conserva el contenido revisado; esta entrega no calcula términos legales ni registra entregas documentales.

Para practicar la fase 4, incorpora las fuentes ficticias del ejemplo después de confirmar sus solicitudes y ejecuta la búsqueda. Deben aparecer reglas para el procedimiento, un registro para recepción y estado, y un pendiente para la copia del acta. [FASE4.md](docs/FASE4.md) explica qué comprobar.

La biblioteca también admite un [archivo histórico de peticiones, respuestas y anexos](docs/HISTORICOS.md), con duplicados por SHA, procedencias, relaciones y advertencias de lectura. Una colección histórica se vincula expresamente al expediente que la va a consultar.

La recomendación de alojamiento es **Drive institucional, preferiblemente una unidad compartida, para la futura biblioteca del equipo**. La aplicación usa almacenamiento local y catálogo SQLite propio. Se incorporó una [selección cotejada de las carpetas de Drive y su membrete](docs/DRIVE.md); conserva enlaces de procedencia y originales locales. La aplicación no sincroniza Drive ni hace respaldos automáticos. [ALMACENAMIENTO.md](docs/ALMACENAMIENTO.md) compara Drive, SharePoint y almacenamiento de objetos.

## Entender lo que hay detrás

La interfaz de 8772 ofrece **Subir PDF** y **Peticiones recibidas desde Gmail**.
La conexión de Gmail se configura desde la propia bandeja, con autorización de lectura
de Google. Admite PDF adjunto, texto del correo y vinculación de seguimientos, conservando
el original y evitando duplicados. [Configuración y prueba de Gmail](docs/GMAIL.md).
La autorización de una cuenta real es un paso posterior a la instalación del código.

Lee [COMO_FUNCIONA.md](docs/COMO_FUNCIONA.md). En la identificación de la aplicación, **Ver cómo funciona este proceso** muestra las etapas y resultados del expediente.

Para seguir el código desde un clic hasta el documento final, consulta [Recorrido del código](docs/RECORRIDO_CODIGO.md): mapa de carpetas, funciones y rutas, búsqueda y redacción en paralelo, decisiones humanas, guardado y exportación.

## Instalación y configuración

Requisitos de este equipo: `uv`, Python 3.12 y navegador. La conversión del oficio a PDF requiere Word de escritorio en Windows; no usa una cuenta de conversión externa. En una instalación nueva:

```powershell
.\scripts\setup.ps1
.\scripts\start.ps1
```

Los scripts usan el Python administrado por uv y las dependencias propias de `.runtime`. Esto evita ejecutar el Python de `.venv`, que el control de aplicaciones de este equipo bloquea. `uv.lock` fija las versiones resueltas.

La clave existente se reutiliza con autorización, leyendo `../langgraph-pqrs/.env.local`. No se copia ni se registra. Se puede indicar otro archivo mediante `PQRS_CLARO_KEY_FILE`. La configuración propia opcional vive en `.env.local` (ignorada por Git); `.env.example` muestra las opciones sin secretos. Si no existe archivo, se admite `OPENAI_API_KEY` del entorno. El modelo se puede cambiar con `PQRS_CLARO_MODEL`.

La identificación, el OCR de peticiones, la evaluación de pertinencia, la redacción y las comprobaciones de respuestas usan OpenAI con `store=False`; el texto o la imagen necesarios se transmiten al proveedor. La biblioteca de fuentes usa OCR local en Windows. La generación del oficio aprobado también es local. La [recuperación de fuentes](docs/RECUPERACION.md) combina búsqueda textual, contexto, identificadores, entidades y embeddings multilingües locales, y recupera respuestas contiguas de los oficios. El modelo semántico se instala explícitamente según [su guía](docs/busqueda-semantica-local.md); si no está disponible, continúa la búsqueda textual con una advertencia. La aplicación escucha únicamente en `127.0.0.1`. No contiene un modo simulado de operación: si falta configuración o falla la IA, muestra el problema.

## Datos y límites

`data/` conserva originales, huellas SHA-256, expedientes, revisiones, biblioteca de fuentes, resultados y checkpoints; está ignorada por Git. Los ejemplos son ficticios y están en `examples/`; `examples/sources/manifest.json` distingue fuentes de demostración y pruebas de estilo/versionado. No se migran ni modifican expedientes del proyecto anterior. La base SQLite activa debe mantenerse fuera de carpetas sincronizadas.

Se admiten PDF de hasta **20 MB, 40 páginas y 120.000 caracteres extraídos**. Superar esos límites detiene el análisis con explicación. Las páginas OCR se marcan para contrastar con la imagen; citar su transcripción no certifica fidelidad visual. La fecha escrita, la fecha de carga y la recepción son campos diferentes; recepción queda sin registrar en esta entrega.

La biblioteca de fuentes admite **PDF, DOCX y TXT de hasta 20 MB**; para PDF, hasta **300 páginas**, y para el texto extraído, hasta **dos millones de caracteres**. DOCX y TXT se consultan por secciones del texto normalizado, no por páginas de Word. La lectura DOCX cubre párrafos y tablas del cuerpo; si son necesarios encabezados, pies, anotaciones o imágenes, utiliza PDF.

Una sola ejecución procesa expedientes a la vez. Al reiniciar, una ejecución incompleta muestra la opción de continuar; una pausa de revisión conserva las correcciones. La versión del expediente evita sobrescrituras silenciosas entre ventanas. La aplicación es local y de un solo proceso; el uso compartido requiere una etapa posterior de usuarios, permisos y operación.

## Comprobar

```powershell
.\scripts\test.ps1
.\scripts\dev-python.ps1 -m ruff check src tests scripts
# Llamadas reales y facturables; solo utilizan PDFs ficticios:
.\scripts\dev-python.ps1 scripts\check_live.py
.\scripts\dev-python.ps1 scripts\check_live.py --case reservado
```

Las pruebas automáticas usan dobles explícitos de IA para validar reglas y reanudación. La comprobación real guarda evidencia en `output/qa/`. [VALIDACION.md](docs/VALIDACION.md) registra qué se verificó en esta entrega y sus límites.
