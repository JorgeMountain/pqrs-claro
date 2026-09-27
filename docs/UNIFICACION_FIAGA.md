# Unificación de PQRS y FIAGA

Fecha: 27 de septiembre de 2026. El código parte de `55ed94a` en ambas copias.

## Uso principal y desarrollo

- Principal: `C:/Users/jorge/Desktop/AgenteO/pqrs-claro`, datos en su `data/`, puerto 8772.
- Desarrollo: `C:/Users/jorge/Desktop/AgenteO/pqrs-claro-fiaga`, con datos separados.
- El laboratorio de texto/PDF de 8775 sigue siendo una herramienta opcional de desarrollo.
- Los puertos 8773, 8774 y 8776 son vistas de desarrollo y QA, no accesos al expediente principal.

El acceso habitual es `scripts/start-unificado.ps1` (o los accesos que lo delegan).
Activa la revisión inicial con OpenAI GPT-6 Luna para clasificación y análisis.
`PQRS_CLARO_MODEL=gpt-6-luna` se configura en `.env.local` de la principal; se conserva
la clave existente. JEV queda como integración opcional, fuera del flujo principal.
No se publican claves ni datos.

## Comportamiento integrado

Tras identificar solicitudes se analiza automáticamente el trámite. OpenAI propone el tipo
de cada petición y evalúa datos, lenguaje, antecedentes y tratamiento especial.
La revisión de lenguaje identifica al emisor de las expresiones ofensivas y no atribuye
automáticamente al solicitante un insulto relatado o citado. Los casos mixtos y ambiguos
requieren valorar el contexto. Se mantiene la revisión humana antes de preparar respuestas.

Los expedientes antiguos no se reprocesan al arrancar. Sus documentos, respuestas y decisiones
permanecen guardados, pero el nuevo flujo exige revisión inicial vigente para continuar,
aprobar o exportar. Una revisión previa desactualizada debe actualizarse explícitamente.
Las dos tablas nuevas son `intake_reviews` e `intake_history`; no se fusionan datos de prueba.

## Respaldo y validación

Respaldo local privado:
`../pqrs-claro-fiaga/output/unificacion-20260927-153642/`.
Incluye código y configuración de ambas copias, bundle Git, bases SQLite respaldadas mediante
su API, documentos y datos de las vistas QA. Dependencias reinstalables y cachés no se duplican.
Las 41 bases copiadas pasaron `integrity_check`.

En una copia de los datos principales se comprobaron 48 originales PDF y las 32 tablas
existentes sin cambios en sus filas; solo se añadieron las dos tablas de revisión inicial.
Esta prueba de conservación no realizó llamadas de IA ni consultas a Gmail.
Evidencias: `manifest.json`, `validation.json` y `tests.xml` en el respaldo.

Para evitar respuestas excesivas en casos pequeños, el límite de salida se calcula por
número de peticiones (mínimo 4.000, máximo 22.000 tokens). Las respuestas incompletas se
rechazan; el límite no garantiza que toda llamada finalice. Las pruebas sintéticas de
cita, insulto directo y mensaje mixto respondieron según lo esperado con OpenAI.

## Recuperación

Si hubiera una regresión, detener el proceso principal antes de recuperar datos. No copiar
bases SQLite por encima de una instancia activa. El respaldo incluye el código anterior
en `pqrs-claro/code.zip` y los datos en `pqrs-claro/data/`. Conservar aparte los datos actuales
antes de cualquier restauración para no perder trabajo posterior a la integración.
El bundle Git conserva los commits anteriores; el ZIP incluye los cambios que estaban
sin commit. Las carpetas `.runtime` continúan disponibles en ambos proyectos.

## Activación con OpenAI

El usuario autorizó completar la integración principal usando OpenAI el 27 de septiembre.
Se selecciona GPT-6 Luna, ya probado con la cuenta existente. No se fusionan bases de prueba.
Se mantiene el acceso principal en 8772 y el aviso de revisión inicial y confirmación humana.

Respaldo adicional previo a la activación:
`../pqrs-claro-fiaga/output/integracion-openai-20260927-164128/`.
Las 41 bases copiadas pasaron integridad. La validación actual sobre una copia conservó
los 48 PDF originales y las filas de las 32 tablas anteriores; solo añadió las dos tablas
para revisión inicial. Las comprobaciones actuales aprobaron 42 pruebas Python y 18 JavaScript.
La batería general anterior aprobó 1.244 pruebas, con una omitida por modelo semántico ausente.

El caso sintético del flujo completo se ejecuta en `validation-data` mediante el puerto
provisional 8777; la evidencia se conserva en `smoke-review.json`. No se confirma ni prepara
una respuesta en nombre de un funcionario. Las comprobaciones del arranque principal quedan
en `activation.json` junto al respaldo; su existencia y contenido son la evidencia de activación.
