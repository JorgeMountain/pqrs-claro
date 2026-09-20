# Entrada de peticiones desde Gmail

La interfaz de **8772** conserva la carga manual de PDF y añade **Peticiones recibidas**
en el inicio y **Peticiones por correo** en el menú lateral. La consulta es manual y
filtrada por una etiqueta, inicialmente `PQRS-Pruebas`. No hay vigilancia programada.

## Conectar una cuenta

1. Abre [Google Cloud](https://console.cloud.google.com/), crea o selecciona un proyecto
   y habilita **Gmail API**.
2. Configura **Google Auth Platform** (nombre de la aplicación, contacto y audiencia).
   Si usas audiencia externa en modo de prueba, agrega como usuario de prueba el correo
   que vas a conectar. Para una cuenta institucional, la política de la organización
   puede requerir autorización del administrador.
3. Crea un cliente OAuth de tipo **Aplicación de escritorio** y descarga su JSON.
4. En el sistema, abre **Peticiones recibidas → Abrir bandeja de Gmail**, selecciona
   ese JSON y pulsa **Guardar configuración**. No debes pegar la contraseña de Gmail.
5. Pulsa **Conectar con Google**, elige la cuenta y autoriza la lectura. Regresa al
   sistema; se mostrará la dirección que Google confirmó.
6. En Gmail, crea la etiqueta `PQRS-Pruebas` y aplícala a los mensajes de prueba.
   En el sistema pulsa **Consultar correos**. También puedes escribir otra etiqueta
   existente. Si no existe, no se amplía la búsqueda al buzón completo.

Inicia el sistema con `scripts/start-recorrido.ps1` o `scripts/start.ps1`;
ambos usan ahora un único proceso en 8772. El retorno
local es `http://127.0.0.1:8772/api/gmail/oauth/callback`. Usa el navegador habitual
si Google no admite iniciar sesión dentro de un navegador integrado.

El permiso solicitado es `gmail.readonly`: Google autoriza lectura del buzón; la
etiqueta es un filtro de la aplicación, no un permiso limitado a esa etiqueta.
No se solicita capacidad para enviar, borrar ni modificar etiquetas o estados.
**Desconectar** elimina el token de este equipo y cancela el intento de conexión;
conserva los expedientes y correos ya copiados. Para retirar además la autorización
en Google, usa la gestión de aplicaciones conectadas de tu cuenta.

En aplicaciones externas en modo de prueba, Google puede limitar la vigencia de la
autorización. Si expira, desconecta y conecta de nuevo. Esto no borra los expedientes.

## Qué se puede importar

- **PDF adjunto:** eliges el PDF que constituye la petición. Se conserva byte por
  byte como documento principal y se mantiene también el correo original.
- **Texto del correo:** confirmas que contiene la petición completa. El sistema
  conserva el `.eml` y crea una copia de consulta en PDF, identificada como tal,
  para reutilizar lectura, tarjetas y resaltado. No inventa un PDF original del remitente.
- **Seguimiento de un caso:** puedes vincular el mensaje a un expediente existente.
  No cambia su PDF, su versión ni sus respuestas. El correo y sus adjuntos quedan
  consultables en **Ver correos del expediente**, en el paso 1.
- **Aviso con enlace:** el enlace no se visita ni se interpreta como petición completa.
  Obtén el documento principal o vincula el aviso a un expediente existente.

El sistema propone números explícitos precedidos por Caso, PQRS o Radicado y permite
corregirlos antes de importar. Con varios candidatos, el campo queda en blanco.
Si hay otro expediente de correo con el mismo número registrado, muestra una sugerencia;
no une expedientes automáticamente. El número registrado precarga el campo editable
de radicado del oficio. El ID técnico local sigue siendo independiente.

La recepción en Gmail, la fecha del encabezado y la fecha institucional de recepción
son datos distintos. El conector conserva las dos primeras; **no llena `received_at`**
ni deduce el peticionario del remitente de una notificación o reenvío.

Los demás adjuntos se conservan dentro del original `.eml` y se pueden descargar.
No se incorporan automáticamente a la biblioteca como fuentes verificadas. Puedes
agregarlos con el mecanismo de evidencia ya existente cuando corresponda.

## Prueba de extremo a extremo

1. Desde otra cuenta, envía un correo a la cuenta conectada con asunto
   `[PRUEBA PQRS] Caso 001 — Solicitud de información`, un texto ficticio y un PDF ficticio.
2. Aplica `PQRS-Pruebas` en Gmail y consulta la bandeja desde el sistema.
3. Abre el mensaje, verifica remitente, número y PDF; pulsa **Crear expediente y analizar**.
4. Comprueba que se abre la etapa 1. La confirmación de solicitudes y la preparación
   posterior siguen funcionando igual que en la carga manual.
5. Vuelve a consultar e importar el mismo mensaje: debe abrir el expediente existente.
6. Envía otra prueba sin adjunto, confirma que el cuerpo contiene la petición completa
   e impórtala desde texto.
7. Envía un seguimiento del Caso 001 y vincúlalo expresamente al expediente existente.
8. Carga también un PDF desde el inicio para comprobar que ambas entradas permanecen disponibles.

Consultar mensajes e importarlos no llama a la IA. La acción **Crear expediente y
analizar** inicia después el análisis normal, que utiliza el proveedor configurado.
La identificación y aprobación humanas siguen siendo necesarias. No hay envío
automático de respuestas al remitente ni conexión automática a OnBase.

## Código y persistencia

- `gmail_auth.py`: OAuth con `state` de un solo uso y diez minutos de vigencia, PKCE
  S256, actualización de tokens y peticiones a endpoints fijos de Google.
- `gmail_content.py`: lectura MIME, conversión de HTML a texto inerte, adjuntos y
  copia de consulta del cuerpo. No carga imágenes remotas ni ejecuta HTML recibido.
- `gmail_service.py`: filtro por etiqueta, paginación, copia original, deduplicación
  por cuenta/mensaje, importación y vinculación.
- `gmail_api.py`: configuración, autorización, bandeja, importación y descargas locales.
- `static/recorrido/gmail-inbox.js`, `gmail-views.js`, `gmail.css`: interacción y vista.

Se usa `gmail_messages` en `expedientes.sqlite`. Cada mensaje consultado en detalle
conserva su `.eml` y SHA-256 en `data/gmail/messages/{id}/original.eml`; los metadatos
incluyen cuenta, ID de Gmail, hilo, Message-ID y fechas disponibles. No se usa el
número de caso como clave de deduplicación.

La creación desde correo usa un ID estable para recuperar un fallo entre la creación
del expediente y el guardado del vínculo, sin crear una segunda petición. La importación
está serializada en el proceso local. El cambio de cuenta invalida una selección de
mensaje de la cuenta anterior. El original se comprueba antes de utilizarlo.

El cliente OAuth y los tokens se protegen con **DPAPI del usuario de Windows** en
`data/gmail/connection/`. No hay alternativa silenciosa que los guarde en texto plano.
Los endpoints de estado no devuelven tokens. El acceso HTTP del launcher de 8772 no
registra las URLs de retorno OAuth. `data/` está excluida de Git.

Límites: diez mensajes por página de consulta; correo original de hasta 30 MB; PDF
principal sujeto a los límites existentes (20 MB, 40 páginas); cuerpo de hasta
120.000 caracteres, con límite adicional de 40 páginas en su copia PDF.

## Validación y alcance

`tests/test_gmail.py` utiliza un transporte doble de Google y datos temporales.
Comprueba autorización, PKCE, vencimiento/reutilización de estado, renovación de token,
filtro, paginación, importación de PDF/texto, duplicados, recuperación, vinculación,
cuenta cambiada, integridad, HTML inerte y protección local. La validación local
no equivale a haber conectado una cuenta real: el usuario debe completar la autorización
y realizar la prueba de recepción con el proveedor.

Referencias oficiales: [OAuth para aplicaciones instaladas](https://developers.google.com/identity/protocols/oauth2/native-app),
[lectura de mensajes](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/get)
y [listado filtrado](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/list).
