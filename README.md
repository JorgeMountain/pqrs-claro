# Gestión de Peticiones · PQRS Claro

Asistente local para recibir documentos PQRS, identificar y clasificar sus peticiones,
buscar respaldo documental y preparar respuestas y oficios con revisión humana.

La interfaz y la API se sirven juntas en **http://127.0.0.1:8772**.
El flujo actual tiene cuatro etapas: **Preanálisis → Identificación → Redacción → Borrador**.

## Empezar en otro equipo

Necesitas Windows, PowerShell, [uv](https://docs.astral.sh/uv/) y Python 3.12.
Microsoft Word de escritorio es necesario para convertir el oficio a PDF.
Node.js se utiliza únicamente para las pruebas JavaScript.

```powershell
git clone https://github.com/JorgeMountain/pqrs-claro.git
Set-Location pqrs-claro
uv python install 3.12
.\scripts\setup.ps1
Copy-Item .env.example .env.local
```

Edita `.env.local` con una clave OpenAI propia y autorizada; después inicia:

```powershell
.\scripts\start.ps1
```

Abre **http://127.0.0.1:8772** y selecciona o crea un gestor.
En una instalación nueva la bandeja y la biblioteca están vacías. Puedes cargar un
PDF ficticio de `examples/`. Al seleccionar el documento, elige **Agregar al pool**
para dejarlo disponible sin asignar o **Iniciar análisis** para abrir su preanálisis
como gestor responsable. La identificación comienza cuando confirmas la revisión. Las operaciones de IA necesitan
configuración y pueden consumir saldo del proveedor.

**Guía completa:** [instalación, configuración y transferencia](docs/ENTREGA.md).
**Para desarrollar:** [CONTRIBUTING.md](CONTRIBUTING.md).
**Todas las guías:** [índice de documentación](docs/README.md).

## Flujo de trabajo

| Etapa | Qué hace el sistema y qué revisa el gestor |
| --- | --- |
| Preanálisis | Datos del solicitante, contenido respetuoso y legibilidad/integridad. Se consulta el original antes de iniciar. |
| Identificación | Extrae las peticiones, propone sus tipos y permite corregirlas y confirmar su revisión conjunta. |
| Redacción | Busca fuentes, evalúa el respaldo y prepara respuestas. El gestor consulta citas, aporta evidencia, atiende pendientes aplicables y revisa los textos. |
| Borrador | Reúne las respuestas, permite editar el oficio y aprobar/generar Word y PDF. «Finalizar expediente» lo mueve a Finalizadas. |

Las etapas disponibles se pueden consultar recuperando su avance guardado. Generar
un oficio y finalizar la gestión son acciones distintas. La selección de gestor es
atribución local; no constituye autenticación ni permisos institucionales.

En **Tiempos de gestión**, el equipo puede consultar la duración de los expedientes,
el tiempo activo estimado de cada gestor y descargar ambas vistas en CSV.
Las reglas de medición se describen en la [guía de la bandeja](docs/BANDEJA_GESTORES.md#tiempos-de-gestión).

## Estructura

```text
src/pqrs_claro/             API, servicios, grafos, motores y persistencia
  static/recorrido/         Interfaz principal en HTML, CSS y JavaScript
  static/demo/              Recursos mínimos para arrancar una copia limpia
tests/                      Pruebas Python y JavaScript
scripts/                    Instalación, arranque y validaciones
examples/                   Peticiones y fuentes ficticias para practicar
docs/                       Guías funcionales, arquitectura e informes fechados
pyproject.toml + uv.lock     Dependencias y versiones resueltas
.env.example                Plantilla sin claves
```

`data/`, `output/`, `tmp/`, `.runtime/`, `.venv/` y los archivos `.env` locales
permanecen fuera de Git. La clonación entrega código y ejemplos ficticios; los
expedientes y la biblioteca se transfieren por separado cuando corresponda.

Para seguir el código: [guía para colaborar](docs/GUIA_PARA_ENTENDER_Y_COLABORAR.md)
y [arquitectura con diagramas](docs/GUIA_VISUAL_PQRS_CLARO.md).

## Configuración y datos

- OpenAI procesa la extracción/interpretación, evidencia y redacción con `store=False`.
  El contenido necesario se transmite al proveedor configurado.
- El clasificador de tipos admite `openai` o `jev`. La plantilla usa `openai` para
  comenzar con una sola credencial; [JEV](docs/JEV_CLASIFICACION.md) es opcional y usa
  una clave TypeSafe propia. La configuración local existente se conserva.
- La búsqueda combina texto, identificadores, contexto y embeddings locales.
  El [modelo semántico](docs/busqueda-semantica-local.md) se descarga explícitamente.
  Mientras falta o se prepara, los otros canales siguen disponibles y se informa su alcance.
- El lector de fuentes usa Fast por defecto en todos los expedientes. Para volver al
  modo habitual, pon `PQRS_CLARO_SOURCE_SERVICE_TIER=default` en `.env.local` y
  reinicia la aplicación. Para reactivar Fast, cambia el valor a `fast`.
- El buscador atiende un expediente por turno y, por defecto, busca respaldos para
  **hasta cinco preguntas de ese expediente a la vez**. Puedes elegir un límite
  de 1 a 5. Para volver a tres, pon `PQRS_CLARO_SOURCE_CONCURRENCY=3` en
  `.env.local` y reinicia la aplicación. La redacción tiene su propio límite en
  `PQRS_CLARO_DRAFT_CONCURRENCY`, con tres por defecto. El entorno del proceso
  tiene prioridad sobre `.env.local`. Puedes comprobar los límites activos en
  los campos `source_concurrency` y `draft_concurrency` de `GET /api/config`.
- [Gmail](docs/GMAIL.md) requiere una conexión propia; no se transfieren tokens.
- Los originales, decisiones, respuestas, aprobaciones y checkpoints se guardan en
  SQLite y archivos de `data/`. Cambiar únicamente el puerto no aísla los datos.

El sistema escucha en `127.0.0.1` y se opera como aplicación local. La integración
con QFDocument/Oracle y el despliegue institucional multiusuario requieren trabajo
adicional. Una fuente encontrada no certifica por sí sola un hecho ni sustituye la
revisión humana. Consulta [recuperación](docs/RECUPERACION.md) y
[suficiencia](docs/SUFICIENCIA.md).

## Comprobar los cambios

```powershell
.\scripts\test.ps1
.\scripts\dev-python.ps1 -m ruff check src tests scripts
$jsTests = @(Get-ChildItem tests -Filter 'test_*.mjs' -File | ForEach-Object FullName)
node --test @jsTests
```

Las pruebas automáticas utilizan datos temporales y dobles de IA/conversión.
Los scripts `check_*live.py` son validaciones distintas que pueden invocar servicios
reales. Los informes anteriores en `docs/` registran su propia fecha y alcance;
no equivalen a una nueva ejecución ni a una validación institucional.
