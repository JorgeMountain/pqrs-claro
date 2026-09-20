# Integración en un puerto · activa

Implementada el 19 de septiembre de 2026. El modo unificado sirve la interfaz
elegida del recorrido y todas las rutas `/api/` desde la misma aplicación FastAPI.
No crea un cliente HTTP hacia 8770, ni un segundo conjunto de servicios o bases.
Usa los mismos servicios de identificación, fuentes, revisión, Gmail y oficios.

## Arranque habitual

Desde la raíz de `pqrs-claro`:

```powershell
.\scripts\start-recorrido.ps1
```

La dirección es `http://127.0.0.1:8772/`. `start.ps1` y `start-unificado.ps1`
inician el mismo modo; ejecutar de nuevo cualquiera comprueba la instancia
existente sin crear otro servidor. También se puede ejecutar
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
- Los arranques habituales `start-recorrido.ps1` y `start.ps1` usan el modo unificado.
- Para volver temporalmente al modo anterior, cerrar primero el unificado y ejecutar
  `scripts/dev-python.ps1 -m pqrs_claro.app` en una terminal y
  `scripts/dev-python.ps1 -m pqrs_claro.recorrido_app --port 8772 --backend-port 8770`
  en otra. El backend anterior usa 8770 por defecto; comprobar que la configuración
  local no cambie ese puerto. Nunca mantener ambos backends sobre los mismos datos.

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

## Fase 3: activación sobre los datos existentes

El 19 de septiembre se sustituyeron los dos comandos habituales por el arranque
unificado. Se respaldaron diez bases SQLite y se registraron las huellas de 1139
archivos locales antes del inicio. No había servidores anteriores activos.

La aplicación abrió los 47 expedientes existentes. En Edge se consultó la etiqueta
`PQRS-Pruebas` mediante la conexión Gmail existente: Google devolvió tres mensajes.
No se importaron mensajes ni se llamó a IA. Las 49 solicitudes del navegador
fueron a 8772, sin errores HTTP o JavaScript. No fue necesario volver a autorizar Gmail.

Se cerró el servidor con Ctrl+C y se inició nuevamente usando `start.ps1`.
La verificación posterior y las huellas se conservan en
`output/qa/activation-20260919/` (respaldo y evidencia local excluidos de Git).
Después del reinicio las diez bases conservan su contenido exacto y los documentos
originales no cambiaron. La única huella distinta corresponde a `token.protected`:
Gmail renovó su token de acceso mediante la conexión existente. La segunda consulta
de navegador volvió a responder sin errores y mostró los mismos tres mensajes.
Solo debe escuchar 8772. Los informes de fases anteriores conservan sus límites
históricos; esta fase añade la comprobación de Gmail real y del arranque habitual.
