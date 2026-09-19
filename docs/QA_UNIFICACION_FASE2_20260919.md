# Validación de la integración · 19 de septiembre de 2026

La aplicación unificada completó un flujo aislado de PDF a oficio con IA real,
edición en Edge y exportación real mediante Microsoft Word. Se conservó el
arranque habitual de dos puertos; esta validación no activa el nuevo modo.

## Alcance y evidencia

| Comprobación | Resultado |
| --- | --- |
| Entrada PDF e identificación real | Tres solicitudes identificadas |
| Búsqueda y redacción real | Tres respuestas, cero pendientes; sin aprobación automática |
| Editor en Edge | Cambio de cierre, guardado y zoom al 75%; sin errores JavaScript ni peticiones a 8770 |
| Comprobación y aprobación | Tres respuestas aprobadas exclusivamente en el expediente ficticio de QA |
| Word y PDF | Dos páginas; `docx_exact=true`, `pdf_text_match=true`; tres solicitudes y diez párrafos |
| Reapertura de aplicación | Conserva cierre, tres aprobaciones y descargas idénticas; sin clave de IA |
| Gmail con doble explícito | OAuth simulado, importación de cuerpo y PDF, detección de duplicados |

El caso de prueba usa la colección de admisiones copiada a una carpeta aislada.
Modelo configurado durante la ejecución: `gpt-5.6-luna`. Se usó un responsable
ficticio y el texto `PRUEBA AISLADA - NO EMITIR` en el oficio. No se enviaron correos
ni documentos y no se modificaron los expedientes de `data/`.

Los originales y la plantilla institucional se copiaron para QA. El servidor
temporal se ejecutó en 8782, con interfaz y API en el mismo proceso; se cerró al
terminar. La reapertura utilizó esa misma copia aislada.

Evidencia local (excluida del repositorio):

- `output/qa_unified_flow.py`: ejecución HTTP, IA, navegador y Word.
- `output/qa_unified_reopen.py`: reapertura sin clave de IA.
- `output/qa/unified-flow-20260919/result.json` y `restart.json`.
- En esa carpeta: `sources.json`, `editor.png`, `pdf-1.png`, `pdf-2.png`,
  `oficio-qa.docx` y `oficio-qa.pdf`. Se inspeccionaron visualmente las capturas.

## Regresión automatizada

Las fixtures de Gmail, fuentes y oficios ejercitan las interfaces `workspace`
y `recorrido`. Se añadió una prueba de reinicio que conserva identificación y
original sin volver a ejecutar IA. También se mantienen las comprobaciones de
origen/host, persistencia, compatibilidad anterior e invalidación de exportaciones
al modificar respuestas.

La primera ejecución obtuvo 153 pruebas correctas y un fallo intermitente en
el ayudante de espera de `test_preparation.py`: leía un estado `running` antes
de consultar si el trabajador ya había terminado. Se corrigió para leer el
estado después de comprobar la finalización; sus diez pruebas pasaron.

La batería final terminó con **155 passed, 1 warning** en 272,88 segundos.
La advertencia es de deprecación de `BlockingPortal` en Starlette/AnyIO.

Comando de la batería final:

```powershell
.\scripts\dev-python.ps1 -m pytest tests/test_unified_app.py tests/test_gmail.py tests/test_preparation.py tests/test_predraft_preparation.py tests/test_office_workspace.py tests/test_office_service_api.py tests/test_recorrido_library.py tests/test_recorrido_office.py -q
```

Ruff pasó en los módulos de integración y los archivos de pruebas modificados.

## Límite y siguiente fase

Gmail real no fue autorizado ni consultado en esta validación. No se considera
probado el intercambio OAuth con Google en el servidor habitual. La fase 3
debe activar el arranque único en 8772 y verificar allí la conexión existente,
conservar los datos y evitar dos backends simultáneos. El modo anterior sigue
disponible mediante `start-recorrido.ps1`.
