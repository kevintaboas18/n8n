# Conectar tu Instagram (solo lectura)

Esto conecta las skills con **tu** cuenta a través de la API oficial de Meta, solo
para leer: perfil, posts, métricas y, si lo permites, comentarios. No publica, no
responde, no escribe mensajes.

## Estado real, sin adornos

- **Probado:** el cliente (`.claude/skills/ig-connect/igapi.py`) pasa 29 tests
  contra un servidor local que imita a Meta, y una llamada real a
  `graph.instagram.com` con un token falso confirmó que el error de Meta se
  interpreta bien.
- **No probado:** ninguna llamada con un token real. Esa primera prueba eres tú,
  con el paso 7. Hasta entonces no sé si `biography`, `website` o los campos de
  comentarios están disponibles con este tipo de token. El script, si Meta los
  rechaza, los omite y lo avisa en lugar de romperse.
- La interfaz del panel de Meta cambia a menudo. Los pasos siguen la documentación
  oficial, pero los nombres de los botones pueden haberse movido.

## Qué necesitas

- Una cuenta de Instagram **profesional** (Business o Creator) y **pública**. La
  guía de Meta dice que la cuenta que añades a la app debe ser pública.
- Una app de Meta propia. Para leer tu propia cuenta, la tabla oficial de Meta
  indica acceso estándar y sin revisión de la app ("App Review: Not required").
  Otra página de Meta dice que Instagram exige completar la revisión antes de
  acceder a "live data". Si Meta te pide la revisión para tu propia cuenta,
  dímelo: es la contradicción que no pude resolver desde aquí.

## Pasos

1. **Crear la app.** En developers.facebook.com: My Apps, Create App, caso de uso
   **Other**, tipo **Business**, nombre y correo.
2. **Añadir Instagram.** En el panel de la app, producto **Instagram**, Set up,
   **API setup with Instagram business login**.
3. **Añadir tu cuenta.** En esa misma pantalla, añade tu cuenta de Instagram e
   inicia sesión con ella.
4. **Generar el token.** En esa pantalla, junto a tu cuenta, pulsa **Generate
   token**, inicia sesión y cópialo. Según Meta, el token que sale del panel es de
   larga duración: 60 días.
5. **Permisos mínimos.** Para esta fase solo hacen falta `instagram_business_basic`
   (perfil y posts) e `instagram_business_manage_insights` (métricas). Si el panel
   te deja elegir, no actives comentarios, mensajes ni publicar mientras no los
   uses. Si no te deja elegir, dímelo: ese token tendrá más poder del necesario.
   - Leer comentarios exige `instagram_business_manage_comments`. La documentación
     de Meta que leí no distingue entre leer y responder para ese permiso, así que
     hay que asumir que también permitiría responder, ocultar y borrar. El script
     solo lee, pero el token podría más. Por eso viene apagado.
6. **Guardarlo, sin pegarlo nunca en el chat.** En la sesión de Claude Code: menú
   del entorno (en la barra de título), **Edit**, y añade la variable
   `IG_ACCESS_TOKEN`. Si esa pantalla ofrece **Network secrets** (o "API
   credentials"), puedes usarla, pero avísame: no sé si inyecta el valor como
   variable o dentro de la petición, y el script lee la variable. Opcional:
   `IG_TOKEN_ISSUED=AAAA-MM-DD` con la fecha de hoy, para recibir avisos antes de
   que caduque. Abre una sesión nueva: es la que recoge los cambios.
7. **Verificar.** En la sesión nueva, pide `/ig-connect doctor`, o ejecuta
   `python3 .claude/skills/ig-connect/igapi.py doctor`. Debe terminar en
   `VERDICT  READY`. Si no, el propio informe dice qué falla.

## Mantenimiento

- **El token caduca a los 60 días.** Antes de eso, ejecuta `igapi.py refresh`. Meta
  exige que el token tenga al menos 24 horas y no esté caducado. Si pasan 60 días
  sin renovarlo, ya no se puede renovar: hay que generar otro en el panel.
- Si Meta devuelve el mismo token, solo actualiza `IG_TOKEN_ISSUED`. Si devuelve
  uno distinto, el script **no lo imprime** salvo que uses `--print-new-token`,
  porque aparecería en la conversación. Lo más limpio es generar uno nuevo en el
  panel y guardarlo en el entorno.
- Un token solo se puede cambiar desde la configuración del entorno, no desde una
  sesión. Por eso esto sigue siendo un recordatorio tuyo cada ~50 días.

## Seguridad

- **El token es una llave.** Un token con permiso de publicar permite publicar
  como tú. El de esta fase no lo incluye.
- Si el token acabó en un chat, un log o un commit, revócalo y genera otro.
- **El repositorio `kevintaboas18/n8n` es público.** No guardes aquí analíticas ni
  comentarios de otras personas. El script se niega a guardar dentro de un
  repositorio git (`--out`), a propósito.
- `.gitignore` ya excluye `.env` y `*.token`.

## Si algo falla

| salida | significa | qué hacer |
| --- | --- | --- |
| 3 | token ausente, caducado o revocado | generar uno nuevo y actualizar `IG_ACCESS_TOKEN` |
| 4 | falta un permiso | generar un token que lo incluya (el mensaje dice cuál) |
| 5 | límite de peticiones de Meta | esperar y repetir con `--limit` menor |
| 6 | sin red hacia `graph.instagram.com` | revisar el acceso de red del entorno |

## Qué no hace esta fase

Publicar, responder comentarios, mensajes directos, webhooks. Eso viene después, si
quieres, y cada paso tendrá su propia aprobación.
