# DECISIONS.md — registro de decisiones de diseño

Este fichero explica **por qué** el código es como es. Cada entrada es una
decisión con su razón y, cuando aplica, las alternativas descartadas. Las
marcadas con 🤖 son valores por defecto que elegí yo (mentor) sin bloquearte;
cámbialos cuando quieras.

Formato: ADR ligero (Architecture Decision Record).

---

## 0. Nombre: `husk` 🤖

**Decisión:** el paquete se llama `husk` ("cáscara").
**Por qué:** el proyecto es "el scaffold" — la cáscara mínima alrededor del
grano. El grano es el LLM; `husk` es la estructura delgada que lo convierte en
agente. Es neutro (sin dominio), corto e importable (`import husk`).
**Descartado:** `nimbus` (sin significado); `CSI::nano` (ya es dominio-ciber;
eso irá en la capa de plugins de arriba, no en el núcleo neutro).
**Reversible:** sí, con un find-replace. El nombre vive en `pyproject.toml`,
`src/husk/`, los imports y el `HUSK_` de las env vars.

## 1. Layout `src/` + repo propio dentro de `Proyecto_Limpieza/husk/` 🤖

**Decisión:** código en `src/husk/`, y el framework es su **propio repo**
(carpeta `husk/`), separado del dossier de estrategia (`../analisis/`).
**Por qué (src layout):** evita el bug clásico de "los tests importan el código
del directorio en vez del paquete instalado". Con `src/`, para importar `husk`
hay que instalarlo (`pip install -e .`), que es lo que hará un usuario real.
**Por qué (repo separado):** cuando publiques con GitHub Desktop, subes solo
`husk/`. El análisis estratégico interno no va a un repo público.

## 2. Presupuesto de minimalismo como test de CI (principio #1)

**Decisión:** `tests/test_loc_budget.py` falla si el núcleo supera **800 SLOC**
o **3 dependencias** de runtime. Hoy: **488 SLOC, 1 dependencia** (httpx).
**Por qué:** el minimalismo es la tesis del proyecto. Una buena intención en el
README se erosiona; un test que rompe el build es un **invariante verificable**.
Cuento líneas no-vacías y no-comentario, **incluyendo docstrings** (criterio
conservador: nunca infra-cuento para "colar" código).
**Nota:** las dependencias de *build* (hatchling) y de *dev* (pytest) no cuentan
para el presupuesto de 3; ese límite es solo runtime.

## 3. Una sola dependencia de runtime: `httpx`

**Decisión:** httpx y nada más. Hablamos con Docker por su **CLI** (subprocess),
no con la librería `docker` de Python.
**Por qué:** cada dependencia es superficie de ataque, peso y una razón para que
algo se rompa. El SDK de Docker arrastraría mucho para algo que `docker run` y
`docker exec` ya hacen. httpx nos da timeouts y un cliente HTTP decente sin más.
**Descartado:** el SDK oficial de OpenAI (nos ataría a un proveedor y a su ritmo
de releases; la API `/chat/completions` es estándar de facto y la hablamos a
mano en ~42 líneas).

## 4. Loop ReAct propio, sin framework (core/loop.py)

**Decisión:** el bucle es nuestro: pide al modelo → si pide herramientas, las
ejecuta y devuelve observaciones → si no, es la respuesta final.
**Por qué:** es el corazón y debe ser legible de un vistazo (93 SLOC). Un
agente = *prompt + while + ventana de contexto + parser de acciones*. Frameworks
como LangChain esconden esto tras capas de abstracción que no necesitamos.
**Detalle clave:** `_dispatch` **nunca lanza**. Si una herramienta peta, el
error se convierte en una observación de texto para el modelo (que puede
reintentar). Un agente que se cae al primer error no sirve.

## 5. Degradación elegante en vez de excepción (principio #3)

**Decisión:** al agotar el cap de pasos o el timeout, no lanzamos error: pedimos
al modelo **una última respuesta de mejor esfuerzo** sin más herramientas.
**Por qué:** un agente real topa con límites constantemente. "Me quedé sin
presupuesto, aquí está lo que tengo" es infinitamente más útil que un stack
trace. Es exactamente la debilidad que criticamos de otros scaffolds.

## 6. Sandbox de dos niveles con fallback avisado (sandbox/container.py)

**Decisión:** Tier 1 = contenedor Docker efímero (sin red, límites de
CPU/mem/PID, `--rm`, se autodestruye). Tier 0 = subprocess en un tempdir del
host, **con aviso a stderr de que NO hay aislamiento**.
**Por qué:** "seguro por diseño" no puede significar "no arranca sin Docker".
El fallback permite desarrollar y que los tests corran en cualquier sitio, pero
grita que es inseguro para que nadie lo use con comandos no confiables.
**Por qué CLI y no SDK:** ver decisión #3.
**Tu máquina (oct 2026):** no tienes Docker → por defecto caerás en Tier 0. Para
el aislamiento real, instala Docker Desktop (ver README / mensaje final).

## 7. Seguridad genérica, no específica de dominio (core/safety.py)

**Decisión:** la deny-list solo bloquea cosas peligrosas para el **host** sea
cual sea la tarea (`rm -rf /`, `mkfs`, fork bomb, `shutdown`…). Más política
específica = plugin, no núcleo.
**Por qué:** el núcleo es domain-agnostic (principio del reto). Meter reglas de
un dominio concreto aquí rompería esa neutralidad.
**HITL:** `Safety.hitl` es un `callable(prompt)->bool`. Por defecto auto-aprueba
(ejecución no interactiva). La CLI con `--approve` lo cambia por un prompt real.
Las herramientas se marcan `risky=True` para forzar ese gate (la de shell lo
está por defecto).
**Honesto:** la deny-list **no** es la frontera de seguridad — lo es el sandbox.
La deny-list es un filtro barato y un disparador de HITL.

## 8. Gestión de contexto por compactación al 80% (core/context.py)

**Decisión:** estimamos tokens (~4 chars/token) y, al 80% de la ventana,
"compactamos": conservamos system + tarea original + un resumen del medio
(hecho por el propio LLM) + las últimas N turnos.
**Por qué:** las ejecuciones largas desbordan la ventana. Resumir el medio
conserva la información útil y recorta el coste.
**Bug sutil evitado:** nunca dejamos que la cola empiece en un mensaje `role:
"tool"` huérfano — la API lo rechaza si no va justo detrás del `assistant` con
sus `tool_calls`. El `while` de `fit()` lo garantiza. (Hay un test para esto.)
**Límite conocido:** la estimación por caracteres es aproximada. Suficiente para
*decidir cuándo* compactar; no es un tokenizador real (eso añadiría dependencia).

## 9. Logging en JSONL, una línea por evento (cli.py) (principio #4)

**Decisión:** cada evento (run_start, assistant, tool_call, tool_result, denied,
degrade, run_end) es un objeto JSON en su línea.
**Por qué:** auditable y reproducible. JSONL se filtra con `grep`, se diffea, se
reproduce y se parsea en streaming. Por defecto va a stderr; `--log fichero`
lo manda a disco. Nunca mezclamos el log con la respuesta final (stdout).

## 10. Comentarios/README en inglés; este fichero en español 🤖

**Decisión:** el código y el README en inglés (audiencia OSS internacional, es
lo que verá Víctor); `DECISIONS.md` en español (es tu registro de aprendizaje).
**Reversible:** sí. Si prefieres todo en español, dímelo.

## 11. Autoría y URLs del repo ✅ resuelto

**Decisión:** `LICENSE` y `pyproject.toml` usan tu nombre de git
(`Fernando Irún`), y las URLs apuntan a `github.com/fernandoirun/husk` (tu
usuario en GitHub Desktop). El README lleva un badge de CI que se pondrá en
verde cuando GitHub Actions ejecute los tests tras la primera subida.
**Si cambias el nombre del repo** al publicarlo, actualiza esas URLs (README y
`pyproject.toml`).

---

## 12. Revisión adversarial multi-agente y 16 arreglos (12 oct 2026)

**Qué hice:** tras la primera versión, lancé una revisión con 5 agentes
revisores (bucle/protocolo, sandbox, cross-platform/Windows, compactación,
tests/empaquetado) y un verificador adversarial por cada hallazgo (intenta
*refutarlo*; solo sobrevive si es un bug real y reproducible). 16 confirmados,
0 falsos positivos. El revisor de tests/empaquetado no encontró nada.
**Por qué así:** no tengo Python en tu máquina para ejecutar pytest, y aunque lo
tuviera, varias perspectivas independientes cazan fallos que una sola relectura
no ve. Los 16 se aplicaron. Resumen por tema:

- **Robustez del bucle (crash → degradación):** el bucle ya no revienta si el
  proveedor devuelve un `tool_call` sin `id`/`name` (Ollama lo hace); y el
  `provider.chat` del camino caliente ahora está protegido: un 429/500/timeout
  degrada a "mejor respuesta posible" en vez de lanzar traceback. (loop.py)
- **Cliente LLM honesto con respuestas raras:** un HTTP 200 con cuerpo
  `{"error":...}` o `choices:[]` ahora da un `RuntimeError` claro, no un
  `KeyError` opaco. (openai_compat.py)
- **Sandbox que de verdad aísla y termina:** el timeout de `docker exec` ahora
  mata el proceso DENTRO del contenedor (`timeout -s KILL`), no solo al cliente;
  contenedor endurecido (no-root `--user 1000`, `--cap-drop ALL`,
  `--security-opt no-new-privileges`, `--read-only` + tmpfs en /work y /tmp);
  `auto` cae a local si el demonio está apagado (`docker info`); setup con
  timeout (un pull colgado ya no bloquea para siempre); guard de `_cid` None.
  (container.py)
- **Cross-platform / tu Windows:** el fallback local prefiere un shell POSIX
  (sh/bash de Git Bash) y, si solo hay cmd.exe, **se lo dice al modelo** por el
  prompt de sistema (`shell_hint`), para que no emita comandos Linux a ciegas;
  decodificación UTF-8 con `errors="replace"` (los acentos ya no crashean);
  `PYTHONUTF8=1` a los hijos; `print` final tolerante a emojis con stdout
  redirigido; limpieza de temp que respeta ficheros read-only y avisa si falla.
  (container.py, cli.py)
- **Contexto que compacta a tiempo y es portable:** el estimador de tokens ahora
  cuenta `tool_calls` y los specs de herramientas (antes los daba por 0 y nunca
  compactaba a tiempo); la nota de resumen va como `user`, no como 2º `system`
  (algunos Ollama/gateways lo ignoran o rechazan). (context.py)

Coste del endurecimiento: **488 → 609 SLOC** (sigue < 800). Añadí tests nuevos
(`test_provider.py`, casos de `tool_call` sin id/name, degradación por error del
proveedor, estimador que cuenta tool_calls). **Lección**: el primer corte "se ve
bien"; la robustez real (errores de red, respuestas raras del proveedor, tu
propio SO) es donde se gana o se pierde la confianza — justo el lema de Alias:
"Capability is cheap. Trust is owned."

### 12b. Arreglo extra descubierto al ejecutarlo en vivo (backend local Windows)
Al correr la demo en tu Windows real (sin Docker → cmd.exe) saltó un 17º
problema que la revisión estática no podía ver sin ejecutar: pasar el comando
como `["cmd","/c", comando]` hace que Windows (`list2cmdline`) re-escape las
comillas y cmd las malinterprete → `SyntaxError` en `python -c`. **Fix**: en el
backend local escribimos el comando a un **script temporal** (`_husk_cmd.sh` /
`_husk_cmd.cmd`) y ejecutamos el fichero; el shell lo lee de disco y desaparece
todo el problema de comillas, igual en sh que en cmd. **Lección clave**: hay
bugs que SOLO aparecen al ejecutar en el SO real; los tests + la revisión
estática son necesarios pero no suficientes. Verificado en vivo: 23/23 tests
verdes y la demo corre entera en cmd.exe (crea job.py, lo ejecuta, devuelve
20 y 8, exit 0).

---

## Pendiente / próximos pasos
- Ejecutar los tests en real (requiere instalar Python; ver mensaje final).
- Fase siguiente: capa de herramientas especializadas **como plugins** encima de
  este núcleo congelado (eso ya es dominio; va en otro paquete/sesión).
