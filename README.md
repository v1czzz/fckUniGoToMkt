# fckUniGoToMkt

Creo que el temario de la universidad tiene mucha paja.

Este proyecto convierte ofertas de empleo en información util para estudiantes.

La idea es sencilla:

1. Recoger ofertas publicadas en InfoJobs para Castellon de la Plana (u otra ciudad) cuyo requisito sea tener estudios universitarios
2. Extraer el contenido y usar Gemini para convertir cada oferta en insights estructurados sobre el tipo de puesto, el ambito y las habilidades / conocimientos practicos que de verdad están buscando las empresas.

Lo que he implementado (ehem vibe-codeado) hasta ahora:

1. Scraping de ofertas desde InfoJobs.
2. Extraccion de insights estructurados con Gemini.

Faltaría la parte de presentarlo de forma bonita y visual.

## Flujo del proyecto

### 1. Scraping

El script [src/scrape_infojobs_castellon_grado.py](src/scrape_infojobs_castellon_grado.py):

- Navega por las paginas de resultados de InfoJobs con un filtro ya fijado en el url.
- Detecta las URLs de ofertas individuales.
- Extrae de cada oferta estos campos:
  - `title`
  - `company`
  - `requirements`
  - `description`
  - `url`
- Guarda el resultado agregado en un JSON, normalmente `laSalsa/rawData.json`.

Filtros actuales del scraping:

- Ciudad: Castellon de la Plana / Castello de la Plana.
- Estudios: Grado (`educationIds=125`).
- Fuente: InfoJobs.

### 2. Extraccion con Gemini

El script [src/generate_insights_gemini.py](src/generate_insights_gemini.py) lee el JSON del scrape y procesa cada oferta con Gemini para extraer:

- `tipo_puesto`
- `ambito`
- `habilidades_practicas`
- `conocimientos_practicos`

El resultado se guarda en otro JSON, normalmente `laSalsa/insights.json`.

## Instalación

### Opcion recomendada: uv

Desde la raiz del proyecto:

```bash
uv sync
```

### Configurar variables de entorno

El script de Gemini carga automaticamente un archivo `.env`, asi que puedes crear uno en la raiz con este contenido:

```env
GEMINI_API_KEY=tu_clave_aqui
```

Antes de ejecutar el scraping, asegurate tambien de que Firecrawl esta instalado (CLI) y autenticado en tu ordenador.
Lo puedes hacer en https://docs.firecrawl.dev/sdks/cli

## Como usarlo

### Paso 1. Extraer ofertas de InfoJobs

```bash
uv run python src/scrape_infojobs_castellon_grado.py
```

Opciones:

- `--output`: ruta del JSON de salida. Por defecto: `laSalsa/rawData.json`.
- `--max-pages`: numero maximo de paginas de resultados a revisar.
- `--wait-for-ms`: tiempo de espera para que renderice la pagina.
- `--workers`: numero de scrapes paralelos de ofertas.

### Paso 2. Generar insights con Gemini

```bash
uv run python src/generate_insights_gemini.py
```

Opciones:

- `--input`: ruta del JSON de entrada. Por defecto: `laSalsa/rawData.json`.
- `--output`: ruta del JSON de salida. Por defecto: `laSalsa/insights.json`.
- `--model`: modelo de Gemini a usar.
- `--retries`: reintentos por oferta si falla una llamada.
- `--retry-delay`: tiempo base entre reintentos.
