# Cygnus — Holiday Calendar

A responsive company holiday calendar built with FastAPI, PostgreSQL, server-rendered HTML/CSS, and Docker.

## Features

- Monthly calendar and holiday list with date, title, and description
- Username/password sign-in; password hashes stored in the database
- Administrator-only create, edit, and delete actions enforced on the server
- PostgreSQL persistence and Docker Compose local setup
- Health endpoint at `/healthz`
- Cloud Run / Cloud SQL deployment outline

## Requirements

- Docker Desktop running
- Docker Compose v2
- A terminal (PowerShell on Windows is fine)

## Run locally

1. Extract the ZIP and open the `holiday-calendar` folder in VS Code.
2. Copy `.env.example` to `.env`.
3. Edit `.env` and set `ADMIN_PASSWORD` to a unique password of at least 12 characters. Change `SECRET_KEY` to a random string of at least 32 characters. Keep `.env` private.
4. Start the app:

   ```powershell
   docker compose up --build
   ```

5. Open [http://localhost:8000](http://localhost:8000).
6. Sign in using username `admin` and the `ADMIN_PASSWORD` you set in `.env`.

The app creates the initial administrator only if `ADMIN_PASSWORD` is set and no user with `ADMIN_USERNAME` exists yet. If you start without `ADMIN_PASSWORD`, create an admin only after configuring it and recreating the database or use a proper admin-management process. Do not expose an app without an admin account.

### Create employee accounts

There is no public sign-up page. After the app is running, create employee logins from the terminal (you will be prompted for the password):

```powershell
docker compose exec web python -m app.scripts.create_user --username emp001 --display-name "Employee One"
```

To create another administrator, add `--admin`. Only give admin access to trusted calendar managers. Passwords must be at least 12 characters. This CLI tool is intended for local/admin operations; for a deployed Cloud Run app, run it through a controlled administrative process using the same production database connection and environment.

Stop with `Ctrl+C`, then run `docker compose down`. Database data remains in the named Docker volume. To delete local database data too, run `docker compose down -v` (destructive).

## Permission model

- Anonymous visitors can view the calendar.
- Signed-in users can view the calendar.
- Only users with `is_admin=true` can add, edit, or delete holidays.
- No public registration route is provided.

## Run tests

Create a virtual environment, install dev dependencies, and run pytest. The tests use a temporary SQLite database:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -v
```

## Google Cloud deployment outline

**Important:** Cloud resources can incur charges. Configure billing budgets/alerts first; budget alerts do not cap spending. Review your free-trial eligibility and credit expiry. Avoid creating Cloud SQL until you have reviewed its estimate.

1. Create/select a Google Cloud project and configure billing.
2. Install the Google Cloud CLI and sign in:
   ```bash
   gcloud auth login
   gcloud config set project YOUR_PROJECT_ID
   ```
3. Enable APIs:
   ```bash
   gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com sqladmin.googleapis.com secretmanager.googleapis.com
   ```
4. Create a Cloud SQL for PostgreSQL instance and a database/user. Choose a region and instance size only after reviewing costs.
5. Create secrets in Secret Manager for the production `SECRET_KEY`, database credentials/URL, and admin bootstrap password. Use a randomly generated secret key. Never commit production secrets or put them in source control.
6. Create a dedicated service account for Cloud Run. Grant it only the required access, including Cloud SQL Client and Secret Manager Secret Accessor for the specific secrets.
7. Build and push the container. Create an Artifact Registry Docker repository first:
   ```bash
   gcloud artifacts repositories create holiday-repo --repository-format=docker --location=YOUR_REGION
   gcloud builds submit --tag YOUR_REGION-docker.pkg.dev/YOUR_PROJECT_ID/holiday-repo/holiday-calendar:latest
   ```
8. Deploy to Cloud Run. Use the same region as the database where practical, attach the Cloud SQL instance, configure secret environment variables, and set `SESSION_HTTPS_ONLY=true` and `APP_ENV=production`. Example (replace placeholders and configure the database URL secret appropriately):
   ```bash
   gcloud run deploy holiday-calendar \
     --image YOUR_REGION-docker.pkg.dev/YOUR_PROJECT_ID/holiday-repo/holiday-calendar:latest \
     --region YOUR_REGION \
     --add-cloudsql-instances YOUR_PROJECT_ID:YOUR_REGION:YOUR_INSTANCE \
     --set-env-vars APP_ENV=production,SESSION_HTTPS_ONLY=true,ADMIN_USERNAME=admin \
     --set-secrets SECRET_KEY=holiday-secret-key:latest,DATABASE_URL=holiday-database-url:latest,ADMIN_PASSWORD=holiday-admin-password:latest \
     --allow-unauthenticated
   ```
   For the Cloud SQL Unix-socket approach used by the command above, set the `DATABASE_URL` secret to this form (URL-encode special characters in the password):
   `postgresql+psycopg://DB_USER:URL_ENCODED_PASSWORD@/holiday_calendar?host=/cloudsql/PROJECT_ID:YOUR_REGION:YOUR_INSTANCE`
   Replace all placeholders. Create the database and DB user in Cloud SQL first. Grant the Cloud Run service account the **Cloud SQL Client** role and Secret Manager access to only the required secrets. If you choose a different connection approach, configure the URL and networking to match it.
9. After deployment, use the Cloud Run URL to verify `/healthz`, login, calendar rendering, and admin CRUD.
10. Review Cloud Run logs, Cloud SQL backups, access controls, and budget alerts.

### Production hardening before real company use

This is a starter project. Before broad production use, add CSRF protection for form submissions, login rate limiting, admin user management/password reset, database migrations (e.g. Alembic), structured audit logs, automated backups, and a documented secret rotation process. Keep Cloud Run and Cloud SQL permissions least-privilege. Do not use the development secret key in production.

## Troubleshooting

- `localhost refused to connect`: check Docker Desktop is running, then `docker compose ps` and `docker compose logs --tail=100 web`.
- DB connection errors: verify `.env` values match and wait for the `db` health check.
- Login doesn't work: verify the `ADMIN_PASSWORD` is set in `.env`; the bootstrap user is created on startup only when a password is set.
- Port 8000 in use: change the left side of `ports` in `docker-compose.yml`, for example `"8001:8080"`, and open `http://localhost:8001`.
