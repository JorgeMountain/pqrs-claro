# Banco aislado de pruebas con Laya y JEV

## JEV en la nube

En `Dónde analizar`, selecciona `JEV · nube de Vercel / TypeSafe` y pulsa
`Enviar a JEV y clasificar`. El texto pegado o extraído del PDF se envía a esos
proveedores. Usa muestras ficticias o anonimizadas. La opción inicial sigue siendo Laya local.

La clave se lee exclusivamente en el servidor desde `AI_GATEWAY_API_KEY` o
`.env.jev.local` (ignorado por Git). No se entrega al navegador. El adaptador usa
`https://ai-gateway.vercel.sh/typesafe/v1/systemone`, modelo `typesafe-ai/jev`,
con ambas preguntas en una llamada. No necesita que Laya esté encendida.

Verificación del 23 de septiembre de 2026: las pruebas automatizadas pasan;
la llamada real fue bloqueada por Vercel con `customer_verification_required`:
exige registrar una tarjeta para habilitar AI Gateway. Aún no se ha validado
una clasificación real de JEV. La presencia de una clave no acredita acceso.

Este espacio está en la copia aislada pqrs-claro-fiaga y se sirve por separado en http://127.0.0.1:8775/. No forma parte del flujo de los puertos 8773 y 8774.

## Iniciar

Desde la raíz C:\Users\jorge\Desktop\AgenteO\pqrs-claro-fiaga:

    .\scripts\start-laya-lab.ps1

El servidor de Laya también debe estar activo en http://127.0.0.1:8770. El banco muestra los modelos que están listos y te deja elegir uno para el tipo de solicitud y otro para lenguaje grosero. Los valores iniciales son `english` para tipo y `multilingual` para lenguaje grosero; se pueden cambiar desde la página.

## Probar una comunicación

Pega texto o sube un PDF. El PDF debe contener texto seleccionable; el banco no aplica OCR. La entrada máxima es de 3.000 caracteres extraídos, 20 páginas y 10 MB. El límite de texto evita recortar contenido sin avisar y reduce problemas con el contexto corto del checkpoint.

Laya devuelve una sugerencia de tipo de solicitud y una señal binaria de posible insulto o lenguaje degradante. Cada una se consulta por separado, con el modelo elegido para esa tarea. La sugerencia cubre el documento como un todo y no separa varias peticiones. La página muestra la distribución completa, la confianza interna, el tiempo y el conteo de tokens. Las probabilidades y la confianza no están calibradas; Laya tampoco explica su etiqueta ni cita el fragmento que la motivó.

Con las instrucciones ajustadas, `english` coincidió con las etiquetas esperadas en seis ejemplos ficticios de tipo. En dos ejemplos sencillos de lenguaje, `multilingual` coincidió con ambas etiquetas y `english` no detectó el insulto explícito. Son muestras muy pequeñas y no permiten inferir rendimiento general; los valores iniciales solo sirven para continuar probando.

## Privacidad y alcance

El banco no escribe solicitudes, PDFs ni resultados en SQLite, carpetas de expedientes, archivos ni almacenamiento del navegador. Extrae el texto del PDF en memoria. Con Laya lo envía a 127.0.0.1:8770; con JEV, a Vercel AI Gateway / TypeSafe, cuyo tratamiento de datos depende de sus políticas. El servidor del banco escucha en 127.0.0.1 y está desacoplado del motor de revisión inicial, Gmail, OpenAI y los datos de FIAGA.

Esto es una prueba exploratoria, no una evaluación operativa. Una queja firme, frustración, crítica o urgencia no constituyen por sí mismas grosería. Contrasta las salidas con ejemplos etiquetados por una persona; no uses el resultado para decidir una petición real.

