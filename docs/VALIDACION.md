# Validación de la entrega 1 — 7 de septiembre de 2026

## Código y persistencia

25 pruebas Python aprobadas en el runtime propio. Cubren lectura nativa, detección de OCR, límites, citas adulteradas, jerarquías, pausa y reanudación en SQLite real, edición humana, escritura obsoleta, protección entre orígenes y rutas del original/imagen. Ruff sin hallazgos y los tres módulos JavaScript pasan `node --check`.

Las pruebas automatizadas sustituyen OpenAI por dobles explícitos. Se observó un aviso de deprecación de `BlockingPortal` emitido por Starlette/AnyIO dentro del cliente de pruebas; no es un error de ejecución del proyecto.

## OpenAI real

Modelo configurado: `gpt-5.6-luna`. Se ejecutaron exclusivamente documentos ficticios. El caso reservado se ejecutó por separado después de las instrucciones iniciales.

| Caso | Observado | Resultado |
|---|---|---|
| Principal | 3 solicitudes en las páginas esperadas; fecha literal | Conforme |
| Subapartados | Padre, dos apartados en distintas páginas y otra solicitud | Conforme |
| Sin fecha | 1 solicitud; nombre y fecha ausentes | Conforme |
| Escaneado | 1 solicitud, OCR señalado y advertencia de revisión | Conforme |
| Sin solicitudes | Detención explícita; ninguna petición inventada | Conforme |
| Reservado | 2 solicitudes, referencias y fecha esperadas | Conforme |

Evidencia local: `output/qa/live-all.json` y `output/qa/live-reservado.json`. Los scripts registran cantidad, coincidencia de términos de la referencia humana en las citas, relaciones, fecha, método de extracción y duración. La fuente de cada cita se comprueba por código. Estas comprobaciones no sustituyen una evaluación semántica amplia ni prueban suficiencia jurídica.

## Aplicación en navegador

Se recorrió la aplicación real en `127.0.0.1:8770` con Playwright:

- Crear el ejemplo ficticio, completar el análisis con IA real y localizar la solicitud de acta en página 2.
- Editar el título de esa solicitud, guardar y recargar: versión y texto conservados.
- Detener y volver a iniciar únicamente el servidor nuevo: la revisión continuó en versión 6, con el título humano conservado. Después se confirmó desde la pantalla y llegó a versión 8.
- Cargar `sin_fecha.pdf` mediante el selector real de archivos, analizarlo, incorporar una solicitud manual con referencia de líneas y guardarla. Retirar luego esa incorporación de prueba y conservar nuevamente la única solicitud del ejemplo.
- Cambiar la solicitud seleccionada y verificar que el original se alinea con su página.
- Revisar consola y red: sin errores ni advertencias de consola; las solicitudes del recorrido respondieron correctamente.
- Inspeccionar 320, 768, 1024 y 1440 píxeles: sin desbordamiento horizontal. Inspección visual de las capturas de móvil y escritorio.
- Axe con reglas WCAG 2 A/AA y 2.1 AA: sin infracciones en la vista confirmada y la vista de revisión verificadas. Inspección de etiquetas, estructura y acceso por teclado. No equivale a una auditoría completa con lector de pantalla.

Capturas: `output/playwright/`. Los seis PDFs ficticios también se renderizaron e inspeccionaron en `output/qa/examples.png`, incluyendo todas sus páginas.

## Límites de esta evidencia

Esta es la primera entrega local. Se evaluaron seis escenarios ficticios y dos expedientes en el navegador; aún hace falta ampliar el conjunto con documentos representativos del trabajo real. El OCR requiere contraste con la imagen. No se validaron corpus normativos, redacción de respuestas, generación de oficios, Drive, correo ni funcionamiento multiusuario: corresponden a etapas posteriores.
