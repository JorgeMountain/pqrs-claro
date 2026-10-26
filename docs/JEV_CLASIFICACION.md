# JEV 1.14 en la clasificación de Identificación

Luna conserva la extracción de solicitudes, su jerarquía y sus referencias del PDF.
Después, JEV `jev-1.14.0` propone una de las once categorías para cada solicitud.
La persona revisa y confirma antes de continuar. La recuperación y evaluación de
evidencia, la redacción y las comprobaciones conservan el modelo OpenAI configurado.

El conector es `src/pqrs_claro/jev_classification.py`. Usa directamente
`https://api.typesafe.ai/v1/systemone`, una pregunta por llamada y hasta dos llamadas
simultáneas. Recibe título, descripción, numeración, citas reconstruidas de las
páginas originales y el contexto de padres, hijos y referencias a otros numerales.
No envía la biblioteca de evidencia, informes anteriores ni decisiones humanas.
Los límites del contexto se señalan explícitamente; una entrada que exceda el límite
local de tamaño se rechaza antes de enviar. No se activa el modo de contexto extendido.

## Configuración

En `.env.local`, ignorado por Git:

```dotenv
PQRS_CLARO_CLASSIFICATION_PROVIDER=jev
PQRS_CLARO_JEV_KEY_FILE=.env.jev.local
```

El archivo señalado contiene `TYPESAFE_API_KEY`; puede ser una ruta absoluta o
relativa al proyecto. También se admite esa clave como variable de entorno.
Se reutiliza la clave autorizada de las pruebas mediante una referencia al archivo
existente, sin copiar el secreto. El adaptador nunca usa `AI_GATEWAY_API_KEY`.
El laboratorio anterior conserva su conexión Vercel independiente.

`PQRS_CLARO_MODEL=gpt-6-luna` sigue controlando extracción, evidencia y redacción.
Para seleccionar explícitamente el clasificador anterior se puede usar
`PQRS_CLARO_CLASSIFICATION_PROVIDER=openai`; no hay fallback automático entre modelos.
Un valor desconocido se rechaza. El arranque unificado respeta la configuración.

La configuración se carga al iniciar el proceso. Si ya hay un servicio abierto,
hay que reiniciarlo para cargar el cambio; abrir nuevamente el script no reinicia
un proceso existente. `GET /api/config` muestra `initial_classification_provider`,
`initial_classification_model` e `initial_classification_ready`, sin claves.

## Errores, revisión y conservación

Cada petición admite un reintento ante un problema de transporte, HTTP 429 o 5xx.
Una respuesta con otro modelo, identificadores incorrectos, etiquetas inválidas o
probabilidades no válidas se rechaza. El error se muestra y permite reintentar;
no se inventa una categoría ni se llama a Luna para suplirla.

La identificación extraída y el original permanecen guardados. Los resultados
vigentes de solicitudes sin cambios pueden reutilizarse. Cambiar proveedor, modelo,
contrato de clasificación o contexto vuelve obsoleto el análisis correspondiente;
no reclasifica expedientes guardados de forma automática. Los análisis previos y
las decisiones humanas conservan sus datos. Las excepciones de piloto ya autorizadas
mantienen su política existente y se muestran como tales.

Cada resultado conserva modelo, confianza y probabilidades. La interfaz atribuye
el análisis al modelo guardado, aunque la configuración actual sea distinta.
La confianza es una estimación; no sustituye la revisión humana. Las métricas locales
registran TypeSafe, tiempos, intentos y tokens sin textos ni secretos. Uso o caché
no informados permanecen desconocidos; los costos solo se calculan con tarifas
configuradas en el mecanismo de métricas existente.

## Verificación

Las pruebas nuevas cubren configuración, contrato HTTP, contexto y citas,
reintentos y errores, selección exclusiva del proveedor, metadatos, caché y revisión
humana en bases temporales. La verificación de esta instalación se guarda en
`tmp/jev-integration-20261016/`, incluyendo una prueba de conexión con solicitudes
ficticias y la comparación de huellas de las cinco bases originales.

El ensayo previo de 33 casos sintéticos cubrió las once categorías; todas las
respuestas válidas coincidieron con su referencia, con un fallo de conexión JEV.
No evaluó extracción desde escritos completos ni demuestra precisión institucional.
Su informe permanece separado en
`../experiments/jev-real-evidence/classification-v2/INFORME_FINAL.md`.

Contrato y versión: [modelos TypeSafe](https://docs.typesafe.ai/models).
