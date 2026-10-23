# Despliegue de BCAC POC en Google Cloud Run (versión para demo)

Guía paso a paso para **desplegar una demo** de la aplicación en Cloud Run, controlar con **Identity-Aware Proxy (IAP)** quién puede entrar, **encenderla y apagarla** cuando haga falta, y entender qué pasa con los datos que se suben.

> **Alcance.** Esta guía es para una **demo a cliente, no para producción**. Para reducir la complejidad, los datos son **efímeros**: se guardan en el contenedor y **se pierden cada vez que la aplicación se apaga, se reinicia o se vuelve a desplegar**. Si necesitas que los datos sobrevivan, el apéndice A explica cómo añadir un bucket de Cloud Storage. Algunos pasos exigen cambios pequeños en el código y archivos nuevos que **todavía no están en el repositorio** (sección 3). Los comandos `gcloud` cambian de vez en cuando: ante cualquier error, comprueba la sintaxis con `gcloud <comando> --help`.

## Índice

1. [Qué se va a desplegar y qué limitaciones tiene](#1-qué-se-va-a-desplegar-y-qué-limitaciones-tiene)
2. [Requisitos previos](#2-requisitos-previos)
3. [Cambios necesarios en el código](#3-cambios-necesarios-en-el-código)
4. [Despliegue paso a paso](#4-despliegue-paso-a-paso)
5. [Control de acceso con IAP](#5-control-de-acceso-con-iap)
6. [Encender y apagar la aplicación](#6-encender-y-apagar-la-aplicación)
7. [Los datos durante la demo](#7-los-datos-durante-la-demo)
8. [Lista de comprobación antes de la demo](#8-lista-de-comprobación-antes-de-la-demo)
9. [Al terminar: borrarlo todo](#9-al-terminar-borrarlo-todo)
10. [Apéndice A: que los datos sobrevivan (opcional)](#apéndice-a-que-los-datos-sobrevivan-opcional)

---

## 1. Qué se va a desplegar y qué limitaciones tiene

### 1.1 Arquitectura

```
 Persona autorizada (cuenta de Google)
        │  HTTPS (URL https://bcac-xxxx-ew.a.run.app)
        ▼
 Identity-Aware Proxy (integrado en Cloud Run): solo pasa quien tiene permiso
        │
        ▼
 Cloud Run: servicio "bcac"   (1 sola instancia · gunicorn 1 proceso, 8 hilos)
   ├─ Imagen construida con Cloud Build desde el Dockerfile del repositorio
   ├─ Secret Manager → SECRET_KEY, GEMINI_API_KEY, ADMIN_PASSWORD (variables de entorno)
   └─ Datos (documents.json, archivos subidos, vectores) en el sistema de ficheros del
      contenedor → EFÍMEROS
```

No hace falta dominio propio, ni balanceador, ni servidor que administrar: la URL es la que asigna Cloud Run.

### 1.2 Limitaciones que hay que conocer

| Limitación | Detalle | Cómo se maneja en la demo |
|---|---|---|
| **Datos efímeros** | El sistema de ficheros de Cloud Run vive en memoria de la instancia. Se pierde al apagar, reiniciar o redesplegar. Cada arranque empieza **sin ningún documento**. | Preparar los documentos de ejemplo y subirlos al empezar (sección 7). No redesplegar durante la demo. |
| **Una sola instancia** | La aplicación guarda todo en un único `documents.json` y protege el acceso con un bloqueo de hilos dentro de **un proceso**. Además, **cada instancia tendría sus propios datos**: con dos, dos usuarios verían documentos distintos. | `--max-instances=1` y `--workers 1`. **No cambiar.** |
| **Los datos ocupan memoria** | Los archivos subidos cuentan para el límite de memoria de la instancia. | `--memory=2Gi`: de sobra para unos cuantos PDF de demo. |
| **Usuario único en la aplicación** | Todas las personas que pasan IAP entran como `admin` y pueden hacer cualquier acción de cualquier pestaña. No queda registro de quién hizo qué. | Aceptable en una demo con personas de confianza. |
| **Los textos van a Gemini** | El texto de cada PDF subido se envía a la API de Gemini (vectores y análisis de IA) con tu clave. | Usar documentos **ficticios** o con permiso expreso del cliente (sección 7). |
| **Python 3.14** | La aplicación se desarrolla con Python 3.14; no está verificado que todas las dependencias tengan paquete precompilado para Linux con esa versión. | Si la construcción de la imagen falla, bajar a 3.13 o 3.12 en el `Dockerfile`. |

---

## 2. Requisitos previos

- Un **proyecto de GCP** con facturación activa y permisos de *Owner* (o, como mínimo: *Cloud Run Admin*, *Cloud Build Editor*, *Artifact Registry Admin*, *Secret Manager Admin*, *Service Account Admin*, *Service Usage Admin*, *IAP Admin* y *Service Account User*).
- La CLI `gcloud` instalada y autenticada (`gcloud auth login`). **Docker no hace falta**: la imagen se construye en Cloud Build.
- **Las personas que van a entrar necesitan una cuenta de Google** (Google Workspace o Gmail). Si no la tienen, IAP no es viable (ver 5.4).
- Un **grupo de Google** con quienes podrán entrar (recomendado), por ejemplo `demo-bcac@tu-dominio.com`, o la lista de correos.
- La **clave de la API de Gemini** (`GEMINI_API_KEY`). Los análisis de IA y los vectores de duplicidades no funcionan sin ella.
- Acceso al repositorio: `https://github.com/jgarciag-solutions/gencat-bcac-poc`.

Variables que se usan en toda la guía (cámbialas por las tuyas y ejecútalas en la misma terminal):

```bash
export PROJECT_ID="tu-proyecto-gcp"
export REGION="europe-west1"
export SERVICE="bcac"
export ACCESS_GROUP="demo-bcac@tu-dominio.com"

gcloud config set project "$PROJECT_ID"
gcloud config set run/region "$REGION"
export PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format="value(projectNumber)")
```

---

## 3. Cambios necesarios en el código

> **Nada de esta sección está hecho en el repositorio.** Aplícalo y confírmalo en git antes del paso 4.

### 3.1 Servidor de producción

`app.py` termina con `app.run(..., debug=True)`, el servidor de desarrollo, que **no debe usarse en un despliegue**. Añade `gunicorn` a `requirements.txt`:

```
gunicorn
```

El bloque `if __name__ == "__main__":` puede quedarse: gunicorn no lo ejecuta.

### 3.2 Contraseña fuera del código (recomendado)

Hoy `USERS` contiene `admin` / `gencat` en texto plano en el repositorio, y `SECRET_KEY` tiene un valor por defecto conocido (`poc-bcac-clave-solo-demo`).

- **`SECRET_KEY`**: ya se lee de la variable de entorno. Basta con definirla (4.3 y 4.4).
- **Contraseña**: con IAP delante, nadie sin permiso llega a la pantalla de login, así que dejar `admin` / `gencat` es un riesgo bajo **en una demo**. Aun así, no es buena práctica y es un cambio de una línea en `app.py`:

```python
USERS = {
    "admin": {"password": os.environ["ADMIN_PASSWORD"], "name": "Administrador", "role": "Administrador"},
}
```

  Con `os.environ[...]` (sin valor por defecto), la aplicación **no arranca** si falta la variable. Si prefieres no tocar el código, omite este cambio y elimina `ADMIN_PASSWORD` del secreto (4.3) y del despliegue (4.4).

### 3.3 Archivos nuevos en la raíz del repositorio

**`Dockerfile`**

```dockerfile
# Si alguna dependencia no tiene paquete precompilado para esta versión de Python, usa 3.13 o 3.12.
FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# 1 solo proceso: el bloqueo de documents.json es un bloqueo de hilos. NO subir --workers.
# --timeout 0: el límite de tiempo lo pone Cloud Run (--timeout del servicio), no gunicorn.
CMD exec gunicorn --workers 1 --threads 8 --timeout 0 \
    --bind 0.0.0.0:${PORT:-8080} --access-logfile - --error-logfile - app:app
```

**`.dockerignore`**

```
.git
.venv
__pycache__
.env
uploads
vectores
logs
CONTEXTO_PROYECTO.md
deploy.md
```

> `.env` y `.venv` ya están en `.gitignore`, y el despliegue desde código fuente respeta ese fichero al subir los archivos. El `.dockerignore` es una segunda barrera: **la clave de Gemini nunca debe acabar dentro de la imagen.**

### 3.4 Qué **no** hace falta tocar

- `config.json` (departamentos, umbrales, días de revisión) y `normativa/` (PDF de leyes del agente normativo): van en el repositorio y entran en la imagen.
- Las carpetas `uploads/`, `vectores/` y `logs/`: la aplicación las crea al arrancar dentro del contenedor.
- `ProxyFix` y las cookies seguras (necesarios en producción): en una demo con IAP no son imprescindibles.

---

## 4. Despliegue paso a paso

### 4.1 Activar las APIs

```bash
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  iap.googleapis.com
```

### 4.2 Cuenta de servicio del servicio (mínimo privilegio)

No uses la cuenta por defecto de Compute Engine, que tiene permisos amplios. Crea una propia:

```bash
gcloud iam service-accounts create bcac-run --display-name="BCAC Cloud Run (demo)"
export RUN_SA="bcac-run@${PROJECT_ID}.iam.gserviceaccount.com"
```

### 4.3 Secretos (Secret Manager)

Nunca pongas claves en el repositorio ni en la imagen.

```bash
# SECRET_KEY: aleatoria y larga (firma las cookies de sesión)
python3 -c "import secrets; print(secrets.token_hex(32))" | tr -d '\n' | \
  gcloud secrets create bcac-secret-key --data-file=-

# Clave de Gemini
printf '%s' "PEGA_AQUÍ_TU_GEMINI_API_KEY" | gcloud secrets create bcac-gemini-api-key --data-file=-

# Contraseña de la aplicación (solo si aplicaste el cambio 3.2); anótala para la demo
python3 -c "import secrets; print(secrets.token_urlsafe(16))" | tr -d '\n' | \
  gcloud secrets create bcac-admin-password --data-file=-

# La cuenta del servicio solo puede LEER estos secretos
for S in bcac-secret-key bcac-gemini-api-key bcac-admin-password; do
  gcloud secrets add-iam-policy-binding "$S" \
    --member="serviceAccount:${RUN_SA}" --role="roles/secretmanager.secretAccessor"
done
```

> Para ver la contraseña generada: `gcloud secrets versions access latest --secret=bcac-admin-password`.
> Si omites el cambio 3.2, no crees `bcac-admin-password` y quita `ADMIN_PASSWORD=...` de `--set-secrets` en 4.4. En ese caso el usuario de la aplicación sigue siendo `admin` / `gencat`.

### 4.4 Construir y desplegar (un solo comando)

Desde la raíz del repositorio:

```bash
gcloud run deploy "$SERVICE" \
  --source . \
  --region="$REGION" \
  --service-account="$RUN_SA" \
  --no-allow-unauthenticated \
  --ingress=all \
  --min-instances=1 --max-instances=1 \
  --concurrency=8 \
  --cpu=1 --memory=2Gi \
  --timeout=300 \
  --port=8080 \
  --set-secrets="SECRET_KEY=bcac-secret-key:latest,GEMINI_API_KEY=bcac-gemini-api-key:latest,ADMIN_PASSWORD=bcac-admin-password:latest"
```

La primera vez, `gcloud` pide confirmación para crear el repositorio de imágenes (Artifact Registry) y puede tardar unos minutos en construir. Al terminar muestra la URL del servicio.

| Ajuste | Por qué |
|---|---|
| `--source .` | Construye la imagen en Cloud Build a partir del `Dockerfile`; no necesitas Docker en tu equipo. |
| `--max-instances=1` | **Imprescindible.** Una sola instancia = un solo conjunto de datos y un solo bloqueo de hilos. |
| `--min-instances=1` | La instancia está siempre encendida: **sin arranque en frío y sin que se pierdan los datos por inactividad.** Es lo que significa «encendida» en la sección 6. |
| `--concurrency=8` | Igual que los 8 hilos de gunicorn: una petición por hilo. |
| `--timeout=300` | Los análisis de IA son síncronos y pueden tardar decenas de segundos. |
| `--memory=2Gi` | Los archivos subidos viven en memoria; PyMuPDF y numpy también consumen. |
| `--no-allow-unauthenticated` | Nadie puede invocar el servicio sin una identidad con permiso: **solo se entra a través de IAP.** |
| `--ingress=all` | Necesario para que IAP integrado en Cloud Run pueda llegar al servicio. |
| `--set-secrets` | Las claves llegan como variables de entorno desde Secret Manager; nunca están en la imagen. |

### 4.5 Activar IAP

1. **Pantalla de consentimiento OAuth**: *APIs y servicios → Pantalla de consentimiento de OAuth*. Si solo van a entrar personas de tu organización (Google Workspace), elige tipo **Interno**. Si van a entrar personas ajenas, ver 5.4.
2. **Activar IAP en el servicio**: consola → *Cloud Run → `bcac` → pestaña Seguridad → Identity-Aware Proxy*, y activarlo. La consola concede automáticamente el permiso de invocación al agente de servicio de IAP.
   *Alternativa por línea de comandos* (según la versión de `gcloud`; comprueba con `--help`):

```bash
gcloud beta services identity create --service=iap.googleapis.com --project="$PROJECT_ID"
gcloud beta run services update "$SERVICE" --region="$REGION" --iap

# IAP necesita poder invocar el servicio (la consola lo hace sola)
gcloud run services add-iam-policy-binding "$SERVICE" --region="$REGION" \
  --member="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-iap.iam.gserviceaccount.com" \
  --role="roles/run.invoker"
```

3. **Dar acceso** (esto es lo que realmente autoriza a las personas; ver sección 5):

```bash
gcloud iap web add-iam-policy-binding \
  --resource-type=cloud-run --service="$SERVICE" --region="$REGION" \
  --member="group:${ACCESS_GROUP}" \
  --role="roles/iap.httpsResourceAccessor"
```

### 4.6 Primera comprobación

```bash
gcloud run services describe "$SERVICE" --region="$REGION" --format="value(status.url)"
```

Abre esa URL en el navegador: debe pedir la cuenta de Google y, tras entrar, mostrar el login de la aplicación. Si algo falla, mira los registros:

```bash
gcloud run services logs read "$SERVICE" --region="$REGION" --limit=50
```

---

## 5. Control de acceso con IAP

### 5.1 Cómo se decide quién entra

Cada persona que puede entrar tiene el rol **`roles/iap.httpsResourceAccessor`** sobre el servicio. Quien no lo tiene ve una pantalla de «no tienes acceso» de Google, sin llegar a tocar la aplicación. Además, IAP obliga a la autenticación de Google de cada persona (con verificación en dos pasos si su organización la exige).

Tres capas, y hay que pasar las tres:

| Capa | Qué protege | Quién decide |
|---|---|---|
| **1. Invocación de Cloud Run** (`--no-allow-unauthenticated`) | Nadie puede llamar al servicio directamente: llamar a la URL `*.run.app` sin pasar por IAP da **403**. | Administradores del proyecto |
| **2. IAP** | Qué cuentas de Google llegan a la aplicación. | Quien tenga `roles/iap.httpsResourceAccessor` |
| **3. Aplicación** | Inicio de sesión propio (usuario `admin`). | Contraseña en Secret Manager (o `gencat` si no aplicaste 3.2) |

### 5.2 Dar y quitar acceso

```bash
# Dar acceso a una persona, a un grupo o a todo un dominio
gcloud iap web add-iam-policy-binding --resource-type=cloud-run \
  --service="$SERVICE" --region="$REGION" \
  --member="user:ana@empresa-cliente.com" \
  --role="roles/iap.httpsResourceAccessor"
#   --member="group:demo-bcac@tu-dominio.com"
#   --member="domain:tu-dominio.com"

# Quitar acceso (mismos parámetros)
gcloud iap web remove-iam-policy-binding --resource-type=cloud-run \
  --service="$SERVICE" --region="$REGION" \
  --member="user:ana@empresa-cliente.com" \
  --role="roles/iap.httpsResourceAccessor"

# Ver quién tiene acceso ahora mismo
gcloud iap web get-iam-policy --resource-type=cloud-run --service="$SERVICE" --region="$REGION"
```

También se puede hacer en la consola: *Seguridad → Identity-Aware Proxy*, seleccionar el servicio y «Añadir principal». Si usas un grupo, dar o quitar acceso es añadir o quitar a la persona del grupo. Un cambio puede tardar unos minutos en aplicarse, y una sesión ya abierta puede seguir viva hasta que caduque.

### 5.3 Acceso con fecha de caducidad (recomendado para una demo)

Puedes añadir una condición de IAM para que el permiso se revoque solo después de la demo:

```bash
gcloud iap web add-iam-policy-binding --resource-type=cloud-run \
  --service="$SERVICE" --region="$REGION" \
  --member="user:ana@empresa-cliente.com" \
  --role="roles/iap.httpsResourceAccessor" \
  --condition='expression=request.time < timestamp("2026-11-05T00:00:00Z"),title=acceso-demo'
```

> La sintaxis de `--condition` cambia entre versiones de `gcloud`: comprueba con `gcloud iap web add-iam-policy-binding --help`. Para quitar un acceso con condición hay que indicar la **misma** condición en `remove-iam-policy-binding`.

### 5.4 Si los asistentes son ajenos a tu organización

- Cada persona necesita una **cuenta de Google** (Workspace o Gmail). Si el cliente no la tiene, IAP no sirve.
- La pantalla de consentimiento OAuth de tipo **Interno** solo admite cuentas de **tu** organización. Para dar acceso a personas ajenas hay restricciones que dependen de cómo se configure el cliente OAuth de IAP (por ejemplo, tipo «Externo»). **No he podido verificar cuáles aplican a IAP integrado en Cloud Run en tu configuración.**
- **Antes del día de la demo, haz una prueba completa con una cuenta ajena a tu organización.** Si no entra, la alternativa más simple es publicar el servicio con `--allow-unauthenticated` y proteger la demo solo con el login de la aplicación (requiere el cambio 3.2 y documentos ficticios).

### 5.5 Qué hace y qué no hace IAP

- **Sí hace:** comprobar la identidad de Google de cada persona y dejar pasar solo a quien tenga el permiso.
- **No hace:** controlar lo que la persona hace dentro. Todos los que pasan entran con el mismo usuario `admin` de la aplicación (sin trazabilidad por persona) y pueden aprobar, rechazar o retirar contenido en cualquier pestaña. No hay protección CSRF. Por eso la demo debe usarse solo con personas de confianza.

---

## 6. Encender y apagar la aplicación

**Sí, es fácil, pero Cloud Run no tiene un botón «pausa».** Un servicio siempre existe; lo que se controla es si hay una instancia ejecutándose y si se puede acceder. Se usan dos ajustes:

| Ajuste | Qué controla |
|---|---|
| `--min-instances` | Si hay una instancia siempre encendida (1) o ninguna cuando no hay tráfico (0). **Es lo que genera coste.** |
| `--ingress` | Si el servicio acepta tráfico de fuera (`all`) o no lo acepta de nadie externo (`internal`). **Es lo que cierra el acceso.** |

### 6.1 Apagar (sin coste y sin acceso)

```bash
gcloud run services update "$SERVICE" --region="$REGION" --min-instances=0 --ingress=internal
```

- Una vez que desaparece la instancia (al quedar inactiva), **deja de generarse coste de cómputo**.
- Nadie puede entrar desde fuera, ni siquiera con permiso en IAP.
- **Los datos se pierden** (efímeros): la instancia desaparece al quedar inactiva. La próxima vez empezará sin documentos.

### 6.2 Encender

```bash
gcloud run services update "$SERVICE" --region="$REGION" \
  --min-instances=1 --max-instances=1 --ingress=all
```

Cloud Run arranca una instancia (puede tardar uno o dos minutos). Normalmente la aplicación empieza **limpia, sin documentos**. Comprueba que responde abriendo la URL con una cuenta autorizada. **Enciéndela con tiempo antes de la demo** (por ejemplo, 30–60 minutos) y haz la comprobación de la sección 8.

> **Si necesitas garantizar que empieza limpia** (por ejemplo, si la apagaste hace menos de unos 15 minutos y la instancia anterior aún podría seguir viva con sus datos), fuerza una revisión nueva: `gcloud run services update "$SERVICE" --region="$REGION" --update-env-vars=RESET=$(date +%s)`. Cambiar una variable de entorno siempre crea una instancia nueva.
>
> **Encender, apagar o actualizar durante una demo puede borrar los datos de la sesión**: cambiar `--min-instances` suele crear una revisión nueva y, con ella, una instancia nueva.

### 6.3 Comprobar el estado

```bash
gcloud run services describe "$SERVICE" --region="$REGION" --format=yaml | grep -E "ingress|minScale|url:"
```

`run.googleapis.com/ingress: internal` y `minScale: '0'` = apagada. `ingress: all` y `minScale: '1'` = encendida.

### 6.4 Otras formas de «apagar»

| Quiero… | Cómo | Efecto |
|---|---|---|
| Cerrar el acceso **sin** tocar la instancia | Quitar el permiso en IAP (5.2) | La instancia sigue encendida (y generando coste); nadie entra |
| Que se apague **del todo** (fin de la demo) | Borrar el servicio (sección 9) | Desaparece todo; volver a crearlo es repetir 4.4 y 4.5 |
| Encender y apagar **automáticamente** a ciertas horas | Cloud Scheduler llamando a la API de Cloud Run Admin | Posible, pero añade complejidad; no se cubre en esta guía |

### 6.5 Costes

Con `--min-instances=1` se paga la instancia mientras esté encendida, aunque no haya nadie usándola; **apágala fuera del horario de la demo**. Con `0`, solo se paga cuando atiende peticiones (y hay una cuota gratuita mensual). Además hay un coste variable por las llamadas a **Gemini**. Estima con la [calculadora de precios de Google Cloud](https://cloud.google.com/products/calculator).

---

## 7. Los datos durante la demo

### 7.1 Qué se guarda y dónde

Todo vive en el contenedor, dentro de `/app` (`uploads/`, `vectores/`, `logs/`):

| Dato | Contenido |
|---|---|
| `uploads/documents.json` | Todos los registros de documentos, estados, versiones, fechas, informes de IA |
| `uploads/<archivo>` | Los documentos subidos |
| `vectores/<id>_vectors.json` | Embeddings de cada documento (duplicidades) |
| `logs/ai_responses/` | Respuestas de IA no interpretables (texto de documentos), solo si falla un análisis |

La normativa (`normativa/`) y la configuración (`config.json`) van dentro de la imagen.

### 7.2 Qué los borra

Se pierden **todos** al: apagar el servicio (6.1), redesplegar o actualizar (cualquier `gcloud run deploy`/`update` que cree una revisión), o si la plataforma reinicia o mueve la instancia (poco frecuente, pero ocurre). No hay copia de seguridad.

### 7.3 Cómo prepararlo

- Prepara un **juego de documentos de ejemplo** (PDF) y apunta en una lista qué subir y en qué orden. Tras cualquier reinicio habrá que volver a subirlos.
- Haz una **sesión de ensayo** completa el día anterior o ese mismo día con la aplicación ya encendida: subida, un análisis de IA de cada tipo, aprobar, rechazar, nueva versión.
- Para que la demo empiece limpia, enciende la aplicación (6.2) justo antes: arranca sin documentos.

### 7.4 Privacidad

- **Usa documentos ficticios o con permiso expreso del cliente.** El texto de cada PDF se envía a Gemini para los vectores y los análisis.
- Con la clave de la API no eliges dónde se procesa el texto. Si hay requisitos de ubicación (por ejemplo, UE), habría que usar Vertex AI con región fija, lo que exige cambios en el código (hoy `app.py` exige `GEMINI_API_KEY` o `GOOGLE_API_KEY` antes de lanzar cualquier análisis).
- **Restringe la clave de Gemini** en Google AI Studio o en Cloud Console (solo a la API de Gemini) y ponle un límite de cuota. Cuando acabe la demo, **revócala o rótala**.
- Los datos no sobreviven al apagado, lo que en una demo es una ventaja: no queda nada del cliente almacenado.

> Esta sección es una guía técnica, no asesoramiento legal.

---

## 8. Lista de comprobación antes de la demo

Marca cada punto, con la aplicación **ya encendida** (6.2):

- [ ] La URL `*.run.app` redirige a la pantalla de acceso de Google (IAP) y, tras entrar, muestra el login de la aplicación.
- [ ] Una cuenta **autorizada** entra; una cuenta **no autorizada** recibe el aviso de acceso denegado de IAP.
- [ ] **Se ha probado con una cuenta ajena a tu organización**, si los asistentes lo son (5.4).
- [ ] Llamar a la URL **sin pasar por IAP** (`curl`) da **403**.
- [ ] Se conoce la contraseña de la aplicación (la de Secret Manager, o `admin` / `gencat` si no se aplicó 3.2).
- [ ] Se puede subir un PDF de ejemplo; aparece en la pestaña correcta.
- [ ] Se ejecuta un análisis de IA (por ejemplo «Analitzar amb IA» en el Referente) y devuelve un informe, sin agotar el tiempo de espera.
- [ ] `gcloud run services describe` (6.3) muestra `ingress: all` y `minScale: '1'`.
- [ ] El acceso de las personas tiene caducidad o está anotada la fecha para quitarlo (5.3).
- [ ] Se sabe qué hacer si la aplicación se reinicia a mitad de la demo (7.3): volver a subir los documentos de ejemplo.

---

## 9. Al terminar: borrarlo todo

Para que no quede nada accesible, ni coste, ni datos del cliente:

```bash
# Servicio (se lleva la configuración de IAP y los datos efímeros)
gcloud run services delete "$SERVICE" --region="$REGION" --quiet

# Imágenes construidas (Artifact Registry crea este repositorio con `--source`)
gcloud artifacts repositories delete cloud-run-source-deploy --location="$REGION" --quiet

# Secretos y cuenta de servicio
for S in bcac-secret-key bcac-gemini-api-key bcac-admin-password; do gcloud secrets delete "$S" --quiet; done
gcloud iam service-accounts delete "$RUN_SA" --quiet
```

Además: **revoca o rota la clave de Gemini**, y quita los accesos de personas ajenas si los diste a nivel de proyecto. Si solo quieres pausar la demo y repetirla, basta con apagarla (6.1).

---

## Apéndice A: que los datos sobrevivan (opcional)

Si necesitas que los documentos subidos **persistan** entre apagados y despliegues, hay que montar un bucket de Cloud Storage como carpeta. **Añade complejidad y riesgos**: un bucket montado no ofrece bloqueos entre procesos y el renombrado de `documents.json` no es atómico. `--max-instances=1` sigue siendo obligatorio. Pasos de diferencia:

1. Crear el bucket y darle permiso a la cuenta de servicio:

```bash
export BUCKET="${PROJECT_ID}-bcac-data"
gcloud storage buckets create "gs://${BUCKET}" --location="$REGION" \
  --uniform-bucket-level-access --public-access-prevention
gcloud storage buckets update "gs://${BUCKET}" --versioning
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" \
  --member="serviceAccount:${RUN_SA}" --role="roles/storage.objectUser"
```

2. En el `Dockerfile`, sustituir las dos últimas instrucciones (`COPY . .` y `CMD`) por:

```dockerfile
COPY . .

# Los datos viven en el bucket, montado en /data: uploads/, vectores/ y logs/ son enlaces a él
RUN rm -rf uploads vectores logs \
 && mkdir -p /data \
 && ln -s /data/uploads uploads \
 && ln -s /data/vectores vectores \
 && ln -s /data/logs logs

CMD mkdir -p /data/uploads /data/vectores /data/logs \
 && exec gunicorn --workers 1 --threads 8 --timeout 0 \
    --bind 0.0.0.0:${PORT:-8080} --access-logfile - --error-logfile - app:app
```

3. Añadir a `gcloud run deploy` (4.4):

```
  --execution-environment=gen2 \
  --add-volume=name=data,type=cloud-storage,bucket="$BUCKET" \
  --add-volume-mount=volume=data,mount-path=/data
```

Con esto, los datos sobreviven a apagados y despliegues, y el versionado del bucket permite recuperar versiones anteriores de `documents.json` (`gcloud storage ls --all-versions` y `gcloud storage cp "gs://BUCKET/uploads/documents.json#GENERATION" ...`). **Pero entonces la demo ya no «arranca limpia»**: hay que vaciar el bucket antes de cada demo (`gcloud storage rm "gs://${BUCKET}/uploads/**" "gs://${BUCKET}/vectores/**"`, solo cuando nadie use la aplicación) y borrarlo al terminar.
