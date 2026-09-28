# Despliegue local — Comp AI CRM

Cómo se levantó este CRM en este entorno, y cómo repetirlo en tu máquina o en un
servidor tuyo. La guía oficial está en [`README.md`](./README.md); esto es el
registro de lo que se hizo aquí, incluidas las dos cosas que hubo que ajustar.

## Qué son las tres piezas

| Proceso | Puerto | Qué hace |
| --- | --- | --- |
| `apps/app` (Next.js) | 3000 | La interfaz que abre el comercial |
| `apps/api` (NestJS) | 3001 | HTTP, sesión, tRPC, sincronización de buzones |
| `apps/agent` (eve) | 2000 | El agente de investigación, con su propio reloj |
| Postgres | 5432 | La base de datos de los tres |

Son **independientes**. Lo único en lo que deben coincidir es `DATABASE_URL` y
`BETTER_AUTH_SECRET`: la API firma la cookie de sesión y la app la verifica.

## Arranque automatico en Claude Code web

Este repositorio trae un hook de `SessionStart`. Una sesion nueva prepara todo
sola: instala Node 24, escribe `.env` si falta, instala dependencias, arranca
Postgres, crea las dos bases, aplica migraciones y carga los datos de demo.

- El hook es `.claude/hooks/session-start.sh`. Se registra en `.claude/settings.json`.
- Solo corre en remoto. Comprueba `CLAUDE_CODE_REMOTE`.
- Es idempotente. Una segunda ejecucion no repite trabajo hecho.
- Corre en modo sincrono. La sesion empieza cuando termina. Asi nada arranca
  antes de tener sus dependencias.

Despues levanta los tres procesos:

```sh
./scripts/dev-up.sh
```

El script arranca Postgres si se paro, y cada proceso que no responda. Deja los
registros en `/tmp/crm-logs`. Devuelve el control en segundos.

`bun run dev` no sirve en este entorno. Turbo marca `agent#dev` como interactivo
y se niega a correr sin terminal.

## Como entrar sin cliente OAuth

El inicio de sesion pasa por un proveedor de identidad. No hay forma de sacar
una sesion desde la terminal. Para eso existe:

```sh
bun run --filter=api dev:session
```

Escribe las filas que Better Auth habria escrito. Imprime la cookie que habria
puesto. Se niega a correr con `NODE_ENV=production`.

Pega esa cookie en el navegador y entras en el CRM.

## Arranque manual

## Arranque

```sh
cp .env.example .env          # y rellena los valores de abajo
bun install

docker compose up -d          # Postgres en :5432
bun run db:deploy             # aplica las migraciones
bun run db:seed               # opcional: un pipeline de demostración
bun run dev
```

App en http://localhost:3000, API en http://localhost:3001.

## Los valores que hay que poner en `.env`

| Variable | Qué poner |
| --- | --- |
| `BETTER_AUTH_SECRET` | `openssl rand -base64 32` |
| `ALLOWED_SIGN_IN` | Tu dominio (`tuempresa.com`) o tu dirección |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Un cliente OAuth de Google — ambos o ninguno |
| `AGENT_BRIDGE_SECRET` | `openssl rand -base64 32`, el **mismo** en los tres procesos |
| `AI_GATEWAY_API_KEY` | La clave del modelo. **Sin esto el agente no razona.** |

`ALLOWED_SIGN_IN` es todo el modelo de autorización: si está vacío no entra
nadie, que es la dirección segura en la que fallar.

`DATABASE_URL` ya apunta al Postgres del `docker compose`; no lo toques salvo que
traigas el tuyo.

## Lo que hubo que ajustar en este entorno

Dos cosas, ninguna es un defecto del producto:

**1. Postgres sin Docker.** Este contenedor no tiene demonio de Docker, así que en
lugar de `docker compose up -d` se arrancó el Postgres 16 del sistema con las
mismas credenciales que espera el `docker-compose.yml`
(`postgres:postgres@localhost:5432`, bases `crm` y `crm_test`). En tu máquina usa
Docker y sáltate esto.

**2. Node 24.** `eve` —el runtime del agente— exige Node >= 24 y aquí había v22.
Se instaló Node 24 y el agente se arranca con él. Los otros dos procesos corren
con Bun y no les afecta.

Y un cambio de una línea en el código, explicado abajo.

### El cambio en `apps/agent`

Se añadió `modelContextWindowTokens: DEFAULT_AGENT_MODEL.contextWindowTokens` a
los tres `defineAgent` (`agent/agent.ts` y los dos subagentes).

Por qué: al compilar, `eve` necesita saber la ventana de contexto del modelo, y
si no se la declaras la va a buscar al catálogo de Vercel AI Gateway. La red de
este entorno bloquea ese host, así que el agente no compilaba. Declarar el valor
—que es el que el propio repositorio ya fija en `packages/db/src/settings.ts`—
evita la consulta.

No es un parche sucio: `modelContextWindowTokens` es un campo propio de `eve`, y
`docs/agent.md` ya establece la regla de que *"`lib/model.ts` siempre envía
`modelContextWindowTokens`; eve nunca lo hereda"*. El cambio extiende esa misma
regla a la configuración del agente.

Si actualizas a una versión nueva del CRM, vuelve a aplicarlo o quítalo si tu
despliegue sí llega al gateway.

## La dependencia que no se puede eludir

El agente piensa con un modelo, y el modelo se sirve a través de
**Vercel AI Gateway** (`ai-gateway.vercel.sh`). Este entorno bloquea ese host por
política de red, así que aquí el agente **arranca, atiende y ejecuta su ciclo de
trabajo, pero no puede razonar**.

Para que investigue de verdad necesitas una de estas dos:

- `AI_GATEWAY_API_KEY` en el `.env` (una clave de Vercel AI Gateway), o
- desplegar en Vercel, donde OIDC lo resuelve sin clave que gestionar.

Todo lo demás del agente —la cola durable, el arrendamiento de filas, los
barridos de base de datos, los reintentos— funciona sin red y está verificado.

## Claves opcionales

Ninguna es obligatoria. Cada una **abre un sitio más donde mirar**; sin ninguna,
el agente lee tu propio correo y calendario, que es gratis y es la mejor prueba
que existe.

| Clave | Qué abre |
| --- | --- |
| Context (Ajustes → General) | Logo, industria y el nombre real tras un dominio; y LinkedIn |
| `PERPLEXITY_API_KEY` | Búsqueda web con citas |
| `BLOB_READ_WRITE_TOKEN` | Copiar fotos y logos a almacenamiento propio |
| `REDIS_URL` | Caché compartida entre instancias |
| `CRON_SECRET` | Protege la ruta de sincronización de buzones |

La clave de Context se pide en el onboarding y se cambia en **Ajustes → General**,
porque un administrador que se autoaloja no puede redesplegar para poner una
variable de entorno.

## Comprobaciones

```sh
bun run test          # 1158 tests
bun run check-types   # tsc --noEmit en todo el monorepo
bun run db:test       # crea y migra la base de datos de pruebas
```

Los tests necesitan `TEST_DATABASE_URL` y **se niegan a correr sin ella** — son
tests de integración reales, escriben y borran filas.

Dos avisos sobre la suite, los dos ya resueltos por el hook:

- `Auth (e2e) > lets the sign-in page read what it may offer` afirma
  `google: true`. El fichero de test pone credenciales de respaldo, pero otro
  test congela la configuracion de auth antes, asi que no llegan a aplicarse.
  El CI del repositorio resuelve esto poniendo valores de marcador
  (`.github/workflows/ci.yml`). El `.env` de esta instalacion usa los mismos.
  Cambialos por tu cliente OAuth real cuando lo tengas.
- `retireExhausted > retires no more rows than the limit allows` cuenta filas y
  asume la tabla `agentTask` vacia. Con restos de una ejecucion anterior, falla.
  El hook limpia esa tabla en cada arranque. A mano:
  `psql -d crm_test -c 'TRUNCATE "agentTask" CASCADE;'`.

## Estado verificado en este entorno

| | |
| --- | --- |
| Postgres 16 | `crm` y `crm_test`, migraciones aplicadas |
| Datos | 15 empresas · 45 contactos · 23 negocios · 159 actividades |
| App :3000 | HTTP 200, interfaz completa |
| API :3001 | HTTP 200, base conectada, 21 routers / 160 procedimientos tRPC |
| Agente :2000 | HTTP 200, `dispatch-health` responde `ok:true` |
| Cola de trabajo | Reclama, arrienda y abre sesion. Verificado con una tarea real |
| Tests | 1158 pasan, 0 fallan |
| Tipos y lint | Limpios en los 13 paquetes |
| Hook de sesion | Corre en limpio y es idempotente |
| `dev-up.sh` | Levanta los tres procesos en unos segundos |
| Razonamiento del agente | **Bloqueado**: falta acceso a AI Gateway |

## Poner esto en producción

Tres despliegues y un Postgres. Lo mínimo:

1. `API_URL` y `APP_URL` con los orígenes reales.
2. Si app y API están en subdominios del mismo padre, `AUTH_COOKIE_DOMAIN` al padre.
3. Añade `https://<tu-api>/api/auth/callback/google` a los URI de redirección de Google.
4. `CRON_SECRET` y un programador apuntando a `POST /internal/sync/mailboxes`.
5. El mismo `AGENT_BRIDGE_SECRET` en los tres procesos.

`apps/api/src/generated/server.ts` va commiteado y **`build` no debe regenerarlo**:
el generador necesita una GLIBC más nueva que la de casi cualquier imagen de
construcción. Se regenera en local y se commitea junto al cambio de router que lo
provocó.
