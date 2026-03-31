# GitHub Inactive Repos Detector

Backend en Python + FastAPI que analiza tu cuenta de GitHub y detecta repositorios inactivos.

## 🚀 Quick Start

### 1. Clonar e instalar dependencias

```bash
cd github-inactive-repos
pip install -r requirements.txt
```

### 2. Configurar token de GitHub

Copia el archivo de ejemplo y agrega tu token:

```bash
cp .env.example .env
```

Edita `.env` y reemplaza con tu **Personal Access Token**:

```env
GITHUB_TOKEN=ghp_tu_token_aqui
INACTIVITY_MONTHS=6
```

> **Generar token:** [github.com/settings/tokens](https://github.com/settings/tokens)
> Scopes recomendados: `repo` (para repos privados) o `public_repo` (solo públicos).

### 3. Ejecutar el servidor

```bash
uvicorn app.main:app --reload --port 8000
```

El servidor estará disponible en `http://localhost:8000`.

---

## 📡 API Endpoints

### `GET /inactive-repos`

Retorna los repositorios inactivos del usuario autenticado.

**Query Parameters:**

| Parámetro    | Tipo   | Default | Descripción                                      |
|-------------|--------|---------|--------------------------------------------------|
| `months`    | int    | 6       | Meses de inactividad (1–120)                     |
| `language`  | string | —       | Filtrar por lenguaje (e.g. `Python`, `JavaScript`) |
| `visibility`| string | —       | Filtrar por visibilidad: `public` o `private`    |

**Ejemplo de request:**

```bash
curl "http://localhost:8000/inactive-repos?months=3&language=Python&visibility=public"
```

**Ejemplo de respuesta:**

```json
{
  "total_repos": 42,
  "inactive_count": 12,
  "inactivity_threshold_months": 3,
  "repos": [
    {
      "name": "old-project",
      "url": "https://github.com/user/old-project",
      "last_commit_date": "2024-03-15T10:30:00Z",
      "days_inactive": 371,
      "language": "Python",
      "visibility": "public"
    }
  ]
}
```

### `GET /scan-secrets`

Escanea repositorios en busca de información sensible (AWS Keys, GitHub Tokens, etc.).

**Ejemplo de respuesta:**

```json
{
  "total_repos_scanned": 1,
  "findings_count": 1,
  "repos": [
    {
      "repo_name": "mi-proyecto",
      "findings": [
        {
          "file_path": ".env",
          "secret_type": "AWS Secret Access Key",
          "line_number": 12
        }
      ]
    }
  ]
}
```

### `POST /manage-repo`

Archiva o elimina un repositorio en GitHub. Ideal para limpieza masiva.

**Query Parameters:**
- `action`: "archive" o "delete".

**Body (JSON):**
```json
{
  "repo_name": "old-project",
  "confirm": true // Requerido para borrar
}
```

### `GET /account-audit`

Devuelve un reporte de seguridad con Gists públicos, claves SSH antiguas y Aplicaciones OAuth Autorizadas en GitHub.

**Ejemplo de respuesta:**
```json
{
  "old_ssh_keys": [],
  "public_gists_count": 5,
  "installed_apps": [
    {
      "id": 8573,
      "app_slug": "vercel",
      "repository_selection": "all",
      "permissions": {"metadata": "read"}
    }
  ]
}
```

### `GET /dead-forks`

Analiza repositorios que son bifurcaciones (forks) y detecta los que no se han actualizado recientemente, ideales para borrar.

### `GET /check-leaks`

Consulta la API de HaveIBeenPwned para ver si una dirección de email está expuesta en fugas de datos. Requiere `HIBP_API_KEY`.
```bash
curl "http://localhost:8000/check-leaks?email=tu@email.com"
```

### `POST /clean-reddit`

Se conecta a la API de Reddit (requiere credenciales en `.env` y el módulo `praw`). Sobreescribe comentarios antiguos con texto aleatorio y luego los borra permanentemente para evitar a los archivadores externos.
```bash
curl -X POST "http://localhost:8000/clean-reddit?older_than_days=30"
```

### `GET /`

Health-check. Retorna info del servicio.

### `GET /docs`

Documentación interactiva Swagger UI.

---

## 🏗️ Arquitectura (Módulo a Módulo)

```
app/
├── main.py            → FastAPI app, CORS, logging
├── config.py          → Settings vía variables de entorno
├── github_client.py   → Cliente GitHub API con soporte de acciones y paginación
├── pwned_client.py    → Cliente HaveIBeenPwned
├── reddit_client.py   → Cliente PRAW para borrado de Reddit
├── services/          → Lógica de Negocio por área
│   ├── repos.py       → Inactividad, Escaneo y Forks Abandonados
│   ├── security.py    → Auditoría de Cuenta (SSH, Gists, OAuth, Data Leaks)
│   └── social.py      → Limpieza de Redes Sociales (Reddit)
├── scanner.py         → Regex rules para detección de secretos
├── schemas.py         → Modelos Pydantic (request/response)
└── routes.py          → API REST 
```

**Flujo:** `Request → Routes → Services → GitHubClient → GitHub API`

**Optimizaciones:**
- Usa `pushed_at` del listado de repos como filtro rápido (evita requests innecesarios al endpoint de commits).
- Paginación automática vía header `Link: rel=next`.
- Manejo de rate-limit: detecta `X-RateLimit-Remaining` y espera automáticamente si se acerca al límite.

---

## ⚙️ Variables de entorno

| Variable           | Requerida | Default | Descripción                           |
|-------------------|-----------|---------|---------------------------------------|
| `GITHUB_TOKEN`    | ✅ Sí     | —       | Personal Access Token de GitHub       |
| `INACTIVITY_MONTHS`| No       | `6`     | Meses sin commits para ser "inactivo" |
