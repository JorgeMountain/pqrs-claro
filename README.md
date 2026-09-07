# PQRS Claro

Primera entrega del reinicio del asistente PQRS en LangGraph: **comprender una petición y comprobar lo que entendió el sistema**.

## Empezar

```powershell
cd C:\Users\jorge\Desktop\AgenteO\pqrs-claro
.\scripts\start.ps1
```

Abrir **http://127.0.0.1:8770**. La opción **Practicar con un ejemplo** utiliza un PDF ficticio y llama a OpenAI de verdad. También puedes cargar tu propio PDF y pulsar Analizar. Selecciona una solicitud para contrastarla con la página original; corrige lo necesario, guarda y confirma la identificación.

## Qué incluye esta entrega

- Parte 1: [objetivo, alcance y criterios de aceptación](docs/PLAN.md), con seis PDFs ficticios y referencia humana en [examples/cases.json](examples/cases.json).
- Parte 2: aplicación independiente, contratos de datos, SQLite para expedientes y checkpoints persistentes de LangGraph.
- Parte 3: carga y conservación del PDF original, extracción por página, OCR cuando hace falta, identificación estructurada, referencias literales, corrección y confirmación humana.

**Confirmar identificación** cierra este primer hito. La búsqueda normativa, las respuestas y la generación de oficios pertenecen a las partes 4 a 7. Esta entrega no calcula términos legales ni registra entregas documentales.

## Entender lo que hay detrás

Lee [COMO_FUNCIONA.md](docs/COMO_FUNCIONA.md). En la aplicación, **Ver proceso** muestra las etapas y resultados del expediente.

## Instalación y configuración

Requisitos de este equipo: `uv`, Python 3.12 y navegador. En una instalación nueva:

```powershell
.\scripts\setup.ps1
.\scripts\start.ps1
```

Los scripts usan el Python administrado por uv y las dependencias propias de `.runtime`. Esto evita ejecutar el Python de `.venv`, que el control de aplicaciones de este equipo bloquea. `uv.lock` fija las versiones resueltas.

La clave existente se reutiliza con autorización, leyendo `../langgraph-pqrs/.env.local`. No se copia ni se registra. Se puede indicar otro archivo mediante `PQRS_CLARO_KEY_FILE`. La configuración propia opcional vive en `.env.local` (ignorada por Git); `.env.example` muestra las opciones sin secretos. Si no existe archivo, se admite `OPENAI_API_KEY` del entorno. El modelo se puede cambiar con `PQRS_CLARO_MODEL`.

La identificación y el OCR usan OpenAI con `store=False`; el texto o la imagen necesarios se transmiten al proveedor. La aplicación escucha únicamente en `127.0.0.1`. No contiene un modo simulado de operación: si falta configuración o falla la IA, muestra el problema.

## Datos y límites

`data/` conserva PDFs originales, huellas SHA-256, expedientes, revisiones y checkpoints; está ignorada por Git. Los ejemplos son ficticios y están en `examples/`. No se migran ni modifican expedientes del proyecto anterior.

Se admiten PDF de hasta **20 MB, 40 páginas y 120.000 caracteres extraídos**. Superar esos límites detiene el análisis con explicación. Las páginas OCR se marcan para contrastar con la imagen; citar su transcripción no certifica fidelidad visual. La fecha escrita, la fecha de carga y la recepción son campos diferentes; recepción queda sin registrar en esta entrega.

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
