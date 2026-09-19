# Integración en un puerto · fases 1 y 2

Implementada el 19 de septiembre de 2026. El modo unificado sirve la interfaz
elegida del recorrido y todas las rutas `/api/` desde la misma aplicación FastAPI.
No crea un cliente HTTP hacia 8770, ni un segundo conjunto de servicios o bases.
Usa los mismos servicios de identificación, fuentes, revisión, Gmail y oficios.

## Arranque preparado

Desde la raíz de `pqrs-claro`, para la fase de activación:

```powershell
.\scripts\start-unificado.ps1
```

La dirección es `http://127.0.0.1:8772/`. También se puede ejecutar
`scripts/dev-python.ps1 -m pqrs_claro.unified_app --port 8772`.
El script comprueba si ya hay una instancia unificada; no detiene procesos
ni reemplaza el recorrido anterior si ocupa el puerto. Rechaza el inicio si
detecta el backend anterior para evitar dos procesos usando los mismos datos.

`PQRS_CLARO_DATA_DIR` y la configuración de credenciales conservan su comportamiento.
No hay migración ni copia automática de expedientes. El callback Gmail continúa
en `http://127.0.0.1:8772/api/gmail/oauth/callback`; los puertos alternativos son
para QA sin autorización Gmail real.

## Compatibilidad y alcance

- `create_app()` conserva por defecto la interfaz alternativa del servicio anterior.
- `create_unified_app()` elige la interfaz del recorrido sobre esa misma aplicación.
- Las rutas estáticas se registran después de la API para no ocultarla.
- `recorrido_ui.py` sirve los mismos archivos en ambos modos; no cambia el diseño.
- La protección de origen local, hosts permitidos, caché y descarga de originales
  se aplica desde el servicio integrado.
- El arranque habitual `start-recorrido.ps1` sigue en modo de dos puertos.
  Su sustitución y el retiro de 8770 corresponden a la fase de activación.
- Para volver al modo anterior, cerrar el unificado y usar `start-recorrido.ps1`.
  Nunca mantener ambos backends sobre la misma carpeta de datos.

## Validación de esta fase

35 pruebas pasaron en las suites de aplicación unificada, recorrido anterior,
API de expedientes y Gmail. Cubren PDF, identificación y edición con dobles
de IA, persistencia, origen/host, fuentes, descargas Word/PDF/ZIP con renderizador
de pruebas e invalidación de documentos después de editar una respuesta.
Ruff y el análisis sintáctico del lanzador PowerShell pasaron.

Una prueba de navegador Edge inició y cerró un único servidor en 8782 con una
carpeta temporal: 48 peticiones, todas al mismo origen, sin errores HTTP ni de
JavaScript. Se revisaron inicio, panel Gmail y listado de expedientes. Evidencias
locales en `output/qa/unified-20260919/`.

No se accedió a Gmail real, no se ejecutó IA real ni Word COM y no se modificaron
expedientes existentes. Esta fase no sustituye la validación completa del flujo
real ni activa por sí misma el nuevo arranque habitual.

## Fase 2: validación aislada

El 19 de septiembre se comprobó además el flujo completo con IA real, edición
en Edge, exportación Word/PDF real y reapertura de los datos guardados. Gmail
se validó con un transporte simulado, incluidos PDF, cuerpo y duplicados.
Consulta [el informe de fase 2](QA_UNIFICACION_FASE2_20260919.md).

La fase 3 pendiente es cambiar el arranque habitual, comprobar la configuración
Gmail real en 8772 y retirar el proceso de 8770. No se ha hecho esa activación.
