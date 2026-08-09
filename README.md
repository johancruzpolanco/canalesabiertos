# 📺 Lista de canales TVAbierta (categorizada y automática)

Genera listas **M3U categorizadas** a partir de la API pública de TVAbierta y las
mantiene actualizadas sola mediante **GitHub Actions**.

- **Fuente:** `https://tvabierta.net/api/tv/channels.json` (con respaldo automático a `bb.m3u`)
- **Actualización:** cada 6 horas, sin intervención
- **Dependencias:** ninguna — solo Python 3 de la biblioteca estándar

---

## 🔗 Enlaces de las listas

> Sustituye `USUARIO/REPO` por tu usuario y repositorio de GitHub.

| Lista | URL |
|---|---|
| **Completa** | `https://raw.githubusercontent.com/USUARIO/REPO/main/dist/tvabierta.m3u` |
| Por categoría | `https://raw.githubusercontent.com/USUARIO/REPO/main/dist/categorias/<categoria>.m3u` |
| Catálogo JSON | `https://raw.githubusercontent.com/USUARIO/REPO/main/dist/channels.json` |
| Índice legible | [`dist/CANALES.md`](dist/CANALES.md) |

Pega la URL de la lista completa en **VLC**, **Kodi**, **TiviMate**, **IPTV Smarters**,
**OTT Navigator** o cualquier reproductor compatible con M3U.

---

## 🚀 Puesta en marcha (5 minutos)

### 1. Crear el repositorio

```bash
git init
git add .
git commit -m "Lista de canales TVAbierta"
git branch -M main
git remote add origin https://github.com/USUARIO/REPO.git
git push -u origin main
```

### 2. Dar permiso de escritura al workflow

En GitHub: **Settings → Actions → General → Workflow permissions**
→ marca **Read and write permissions** → **Save**.

Sin este paso el bot no puede publicar los archivos generados.

### 3. Lanzar la primera actualización

**Actions → Actualizar lista de canales → Run workflow.**

A partir de ahí se ejecuta sola cada 6 horas.

---

## 📂 Estructura

```
├── .github/workflows/
│   └── actualizar-lista.yml     # Automatización (cron + manual + push)
├── config/
│   ├── categorias.json          # Códigos de la API → nombres y orden
│   └── nombres.json             # Correcciones manuales de nombres
├── scripts/
│   ├── generar_lista.py         # Generador principal
│   └── resumen.py               # Resumen para el panel de Actions
└── dist/                        # ← Generado automáticamente
    ├── tvabierta.m3u
    ├── channels.json
    ├── CANALES.md
    └── categorias/*.m3u
```

---

## ⚙️ Qué hace el generador

1. **Descarga** el catálogo JSON; si falla, cae al respaldo `bb.m3u` (misma lógica que la web).
2. **Unifica categorías** con `config/categorias.json`. Por ejemplo, la API devuelve
   `Cl` y `CL` como categorías distintas siendo ambas Chile: aquí se fusionan.
3. **Traduce los códigos** a nombres presentables: `RD` → `🇩🇴 República Dominicana`,
   `NEWS` → `📰 Noticias`, `PELICULAS` → `🎬 Películas y Series`.
4. **Corrige los nombres**, que llegan pegados y en minúsculas:
   `misioneltv` → `Misionel TV`, `antena7` → `Antena 7`, `rtvd` → `RTVD`.
5. **Elimina duplicados** por URL de stream y descarta entradas sin stream válido.
6. **Ordena** por categoría (según `orden`) y luego por número de canal.
7. **Escribe** la lista completa, una lista por categoría, el JSON y el índice Markdown.

---

## 🛠️ Uso manual

```bash
# Generación normal
python scripts/generar_lista.py

# Verificar que cada stream responda (tarda unos minutos)
python scripts/generar_lista.py --verificar

# Verificar y descartar los canales caídos
python scripts/generar_lista.py --verificar --excluir-caidos

# Sin emojis, para reproductores que no los renderizan bien
python scripts/generar_lista.py --sin-emojis

# Con guía EPG/XMLTV en la cabecera
python scripts/generar_lista.py --epg "https://ejemplo.com/epg.xml"
```

| Opción | Efecto |
|---|---|
| `--salida DIR` | Directorio de salida (por defecto `dist`) |
| `--verificar` | Comprueba que cada stream responda y marca `activo` en el JSON |
| `--excluir-caidos` | Junto con `--verificar`, omite los canales sin respuesta |
| `--sin-emojis` | Nombres de categoría sin emoji |
| `--epg URL` | Añade `x-tvg-url` a la cabecera M3U |
| `--repo-raw URL` | Base para los enlaces del índice `CANALES.md` |

---

## ✏️ Personalización

### Renombrar, reordenar o agrupar categorías

Edita [`config/categorias.json`](config/categorias.json):

```json
"RD": { "nombre": "República Dominicana", "emoji": "🇩🇴", "orden": 10 }
```

`orden` decide la posición (menor = primero). Para unir dos códigos en una sola
categoría, usa `alias`:

```json
"alias": { "Cl": "CL", "CHILE": "CL" }
```

Cualquier código que no esté definido cae en `por_defecto` (`📺 Otros`), así que
las categorías nuevas de la API nunca se pierden.

### Arreglar el nombre de un canal

Añade la línea a [`config/nombres.json`](config/nombres.json):

```json
"adn40": "ADN 40"
```

> ⚠️ **La clave es el nombre original que devuelve la API, en minúsculas** — no el
> nombre ya corregido. Si la API devuelve `ADN40`, la clave es `adn40`. Puedes
> consultar los nombres originales en el campo `tvg_name` de
> `https://tvabierta.net/api/tv/channels.json`.

Las correcciones manuales tienen prioridad absoluta sobre las reglas automáticas.

### Cambiar la frecuencia

En [`.github/workflows/actualizar-lista.yml`](.github/workflows/actualizar-lista.yml):

```yaml
- cron: "0 */6 * * *"   # cada 6 horas
- cron: "0 */2 * * *"   # cada 2 horas
- cron: "0 5 * * *"     # una vez al día, 05:00 UTC
```

### Activar la verificación de enlaces periódica

La verificación está **desactivada** en las ejecuciones automáticas porque añade
varios minutos. Para usarla manualmente: **Actions → Run workflow →** marca
*Verificar*. Para dejarla siempre activa, añade `--verificar` al paso
`Generar listas M3U` del workflow.

---

## 🔍 ¿Hacen falta proxy, User-Agent o Referer?

**No.** Se comprobó sobre los 431 canales del catálogo:

| Comprobación | Resultado |
|---|---|
| Directivas `#EXTVLCOPT` / `#KODIPROP` en el origen | 0 |
| Cabeceras pegadas a la URL (`\|User-Agent=…`) | 0 |
| Campos de cabeceras/proxy en la API | ninguno (solo 9 campos, todos de metadatos) |
| `xhrSetup` o proxy en el reproductor web | no existe |
| Canales que **solo** responden con `Referer`/`Origin` | **0** |

Los streams son HLS directos y funcionan en VLC, Kodi o cualquier reproductor sin
configuración añadida. En una prueba real, **409 de 431 respondieron HTTP 200 sin
enviar ninguna cabecera**; los ~22 restantes estaban simplemente caídos en origen
(404, 403 o dominio inexistente) y **añadir cabeceras no rescató ni uno solo**.

Dos matices que conviene conocer:

- **Ya hay un proxy, pero del lado del servidor.** Unos 41 canales se
  reemiten a través de la infraestructura de TVAbierta (`hls.tvabierta.net`,
  `ds.tvabierta.net`). Ese trabajo ya está hecho antes de llegar a la lista, así que
  el reproductor no necesita hacer nada.
- **El P2P no se pierde por usar esta lista.** La web usa `p2p-media-loader` para
  repartir ancho de banda entre navegadores; es una optimización exclusiva del
  navegador. VLC o Kodi descargan el HLS directamente, con el mismo resultado en pantalla.

**URLs con acentos:** el catálogo trae alguna ruta como
`.../Cosmovisión/playlist.m3u8`, que varios reproductores rechazan. El generador la
convierte automáticamente a `.../Cosmovisi%C3%B3n/playlist.m3u8` (y aplica IDNA al
dominio si hiciera falta), así que las listas salen siempre en ASCII puro.

Si en el futuro algún canal empezara a exigir cabeceras, se añaden en el M3U así:

```
#EXTINF:-1 group-title="…",Nombre
#EXTVLCOPT:http-user-agent=Mozilla/5.0
#EXTVLCOPT:http-referrer=https://ejemplo.com/
https://…/playlist.m3u8
```

---

## ⚠️ Notas

- **Los workflows programados se pausan** tras 60 días sin actividad en el repositorio.
  GitHub avisa por correo; basta con reactivarlos desde la pestaña Actions.
- El cron de GitHub **no es puntual**: puede retrasarse en horas de mucha carga.
- Este repositorio **solo reorganiza** un catálogo público; no aloja ni redistribuye
  ningún stream. La disponibilidad depende enteramente de TVAbierta y de cada emisora.
