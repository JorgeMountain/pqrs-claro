# Lectura local de anexos escaneados

La biblioteca puede recuperar texto de PDF escaneados con el reconocimiento de texto
instalado en Windows. Los archivos se procesan en el equipo, sin enviar imágenes a OpenAI
ni a otro proveedor. Se necesitan los paquetes Python WinRT del proyecto y un idioma OCR
instalado en Windows; el motor informa los idiomas disponibles antes de empezar.

`WindowsOCR` implementa el proveedor que recibe PNG y devuelve texto para `PDFExtractor`.
Mantiene un proceso Python local durante la lectura, limita cada operación y cierra sus
archivos temporales. No modifica políticas de ejecución de PowerShell ni necesita ese
intérprete. `probe()` comprueba disponibilidad; `close()` libera el proceso.

Las nuevas fuentes PNG/JPG/JPEG cargadas en `SourceLibrary.add` utilizan el mismo
proveedor OCR configurado para la biblioteca. Se decodifica el formato real, se normaliza
un PNG temporal y se conserva una sola sección. Una carga sin motor OCR o sin texto
suficiente devuelve un error claro y revierte el alta, sin registrar texto ficticio.

## Estados y trazabilidad

- `ready`: terminó la lectura técnica de todas las páginas, incluidas las páginas leídas
  por OCR. No significa que una persona haya aprobado la transcripción o su contenido.
- `partial`: hay texto consultable, pero quedaron páginas sin completar.
- `pending`: no se pudo obtener texto consultable.
- Toda página OCR conserva `method=ocr` y `needs_review=true`, aun si el documento queda
  en `ready`. Las cifras, nombres, correos y tablas deben cotejarse con el original cuando
  sean relevantes para una respuesta.

La reextracción conserva los bytes y SHA-256 del original, la numeración de páginas y el
texto nativo ya extraído. Solo procesa páginas vacías o marcadas para revisión. Cuando una
página ya contiene texto, ese texto permanece literalmente al inicio y se agregan líneas
OCR que no aparecen en él; el resultado de esa página requiere cotejo porque puede tener
redundancias o un orden de lectura distinto del diseño visual.

La lectura adicional no modifica `review_status`, `reviewed_by`, `verification_status`,
las decisiones sobre respuestas ni `source_reviews`. Registra `extraction_revision`,
motor/idioma, fecha, acciones y páginas pendientes. El estado actual de las fuentes cambia
para que los análisis que dependían de la extracción anterior puedan identificarse como
desactualizados.

## Reextraer una biblioteca existente

Inventario, sin escritura en la biblioteca:

```powershell
.\scripts\dev-python.ps1 scripts/reextract_sources.py inventory
```

Preparar una propuesta completa, sin aplicar cambios en SQLite:

```powershell
.\scripts\dev-python.ps1 scripts/reextract_sources.py prepare `
  --plan output/ocr-local/propuesta.json
```

El alcance predeterminado son los PDF pendientes o parciales de las colecciones
`onman-20260907` y `drive-pqrs-fuentes`. Se puede limitar con `--collection` y `--source-id`,
repitiendo las opciones. `--language es-ES` elige el idioma instalado. `--resume` continúa
una propuesta interrumpida; no reutiliza una fuente si su estado cambió entretanto.

Para imágenes PNG/JPG/JPEG, usar `--kind images` tanto en inventario como al preparar:

```powershell
.\scripts\dev-python.ps1 scripts/reextract_sources.py prepare --kind images `
  --plan output/ocr-local/propuesta-imagenes.json
```

Cada imagen de un solo fotograma genera la sección 1; conserva `location_kind=section`
y actualiza `page_count=1` como dato derivado del original validado. Los píxeles se
normalizan temporalmente a PNG, con la orientación EXIF, fondo blanco y un máximo de
3200 píxeles por lado (o el límite menor del motor). El original PNG/JPEG y su SHA no
cambian. Si OCR falla, la sección queda pendiente, sin interpretar una imagen como vacía.
El aplicador no permite extender páginas de un PDF usando esta excepción para imágenes.

El umbral mínimo de caracteres detecta salidas vacías, pero no demuestra fidelidad en
escritura manuscrita, fórmulas ni tablas. Antes de aplicar un lote debe cotejarse una muestra
y cualquier transcripción evidentemente deformada. Una salida descartada por cotejo se
conserva solo en el registro de auditoría; su sección mantiene el texto previo y el estado
pendiente, sin convertir caracteres espurios en una fuente consultable.

La propuesta registra las páginas completas y las acciones por página. Se guarda al
terminar cada documento para permitir la recuperación tras una interrupción. Antes de
aplicarla, revisar `source_errors`, `page_events` y `pending_pages`; una extracción vacía
no se interpreta como prueba de inexistencia del documento.

Aplicación explícita de la propuesta revisada:

```powershell
.\scripts\dev-python.ps1 scripts/reextract_sources.py apply `
  --plan output/ocr-local/propuesta.json `
  --backup output/ocr-local/biblioteca-antes.sqlite
```

El respaldo SQLite debe ser nuevo. La aplicación usa una transacción y verifica el
SHA-256 de cada original y la huella del estado previo de cada fuente. Rechaza propuestas
obsoletas, fuera de alcance o que modifiquen campos ajenos a la extracción. La copia previa
conserva la extracción anterior y sus metadatos; los originales siguen en `data/library`.

## Referencias técnicas

- [Motor OCR de Windows](https://learn.microsoft.com/en-us/uwp/api/windows.media.ocr.ocrengine).
- [Operaciones asíncronas de PyWinRT](https://pywinrt.readthedocs.io/en/stable/types.html).
