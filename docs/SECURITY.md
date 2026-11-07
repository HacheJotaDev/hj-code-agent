# Seguridad — HJ CODE AGENT V2

## Modelo de amenazas

El bot ejecuta código generado por un LLM y subido por usuarios dentro del VPS.
Las fronteras de seguridad son capas de software independientes de las
respuestas del modelo: **ningún archivo del proyecto, README o salida del
modelo puede conceder permisos**.

## Capas

1. **Acceso al bot**: solo `user_id` autorizados (`HJ_ADMIN_USER_IDS` + /authorize).
   Todo lo demás se ignora. Auditoría de acciones en `audit_log`.
2. **System prompt**: modo NATIVO por defecto (cero prompts ocultos). La única
   fuente es `core/prompts/service.py`; hay pruebas que lo verifican.
3. **Sandbox de ejecución**:
   - `docker`: contenedor por proyecto, `--cap-drop ALL`, `no-new-privileges`,
     usuario 1000, límites de memoria/CPU/pids/fsize, timeout per-command,
     solo monta el workspace. Sin socket Docker, sin credenciales, sin acceso a
     la base de datos. Red configurable (`HJ_SANDBOX_NETWORK=0` o red dedicada
     `HJ_DOCKER_NETWORK`). Recomendado: **Docker rootless** en el host.
   - `local` (solo desarrollo): `setrlimit` (AS/CPU/NPROC/FSIZE), sesiones de
     proceso propias, kill por grupo. **ADVERTENCIA honesta**: comparte usuario
     y kernel con el host; no garantiza aislamiento frente a código malicioso.
     En producción usa Docker o ejecuta los sandboxes en una máquina aparte.
4. **Command guard** (`security/command_guard.py`): lista de denegación
   (sudo, mkfs, dd a discos, docker/nsenter, curl|sh, acceso a /dev/sd*,
   socket docker...). No es una garantía absoluta: es segunda línea tras el
   contenedor.
5. **Path guard** (`security/path_guard.py`): toda ruta del agente se resuelve
   y limita al workspace; symlinks que escapan quedan bloqueados.
6. **Entorno del sandbox**: lista blanca de variables. Nunca llegan
   `TELEGRAM_BOT_TOKEN`, API keys, `HJ_MASTER_KEY` ni tokens de GitHub
   (verificado en tests).
7. **GitHub**: token guardado cifrado; las operaciones remotas las ejecuta el
   **broker** en el host con credencial efímera (GIT_ASKPASS por entorno) que
   no se escribe en `.git/config` ni en el workspace. El push requiere
   aprobación con botones; autopush OFF por defecto y restringido a ramas
   autorizadas; nunca a ramas protegidas sin lista explícita.
8. **Bóveda**: credenciales cifradas con Fernet; clave maestra externa a la BD
   (`HJ_MASTER_KEY` o archivo 0600). Si la pierdes, las credenciales son
   irrecuperables (documentado; haz copia fuera del VPS).
9. **/setapi**: formulario local de un solo uso en `127.0.0.1` (túnel SSH),
   expira en 10 min. Las API keys nunca viajan por el chat.

## Recomendaciones de despliegue (Contabo 8 GB compartido)

- Usa el instalador systemd: el bot corre junto a tus otros servicios **sin
  tocarlos** (long polling, sin puertos nuevos; el formulario solo escucha en
  loopback).
- Sandbox Docker con `HJ_SANDBOX_NETWORK=0` salvo que la tarea necesite
  instalar dependencias; para máxima contención, red dedicada sin acceso a la
  IP del host y sin volúmenes ajenos.
- Vigila recursos: `deploy.resources` en compose, límites por sandbox en .env.
- Rotación: si un token se compartió en un chat (p. ej. este proceso de
  desarrollo), **revoca y regenera** el PAT/API key.

## Limitaciones conocidas (honestidad > marketing)

- Un contenedor Docker en un kernel compartido no aísla frente a exploits del
  kernel; para código hostil de terceros usa una VM o máquina dedicada.
- La lista de denegación de comandos es orientativa.
- Telegram no es E2E: no envíes secretos al chat; usa el formulario.
