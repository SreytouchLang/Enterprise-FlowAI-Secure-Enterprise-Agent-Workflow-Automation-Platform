# Development

## Containers

1. Copy `.env.example` to `.env`. Keep real API keys outside version control.
2. Start Docker, then run `make dev`. It builds each distinct image once before starting services, which also avoids competing tags with Docker's classic builder. Postgres, Redis, MinIO and Keycloak persist to named volumes. One-shot storage initialization and migration containers prepare dependencies.
3. Run `make seed` once services are running. Seeded identities correspond exactly to the imported Keycloak IDs; rerunning does not create extra identities.
4. Open http://localhost:3000 and authenticate using a documented synthetic account.

The local MinIO container builds the pinned official community source because upstream container/binary distribution is unavailable. Upstream [archived the community repository](https://github.com/minio/minio); this development service is loopback-only and intended for synthetic data. Production uses managed S3. The first source build takes longer than pulling an image.

The MinIO console is http://localhost:9001. Storage credentials in `.env.example` are intentionally public development values. Backend and worker containers use `STORAGE_BACKEND=s3`, so successful uploads involve MinIO; no AWS credentials are required.

The realm fixes its public issuer at `http://localhost:8080/realms/enterpriseflow`. Browser redirects use that address; containers use internal token and JWKS URLs. Do not change the issuer to `http://keycloak:8080`: the browser cannot resolve Docker service names. `ENABLE_DEV_USERS` enables the local seed command, never an authentication bypass.

If you already have old volumes from the scaffold, inspect them before resetting anything. The restricted runtime role and realm import initialize new volumes only. `docker compose down` preserves data; `docker compose down -v` intentionally destroys all local databases, identity state and files.

## Host development

`make setup` creates `.venv` and installs the web dependencies. Start only backing services:

```sh
docker compose up -d postgres redis minio storage-init keycloak
```

For a host API shell, provide overrides pointing at `localhost`; do not source `.env` as shell code. The file is dotenv syntax, including values with spaces.

```sh
export DATABASE_URL='postgresql+psycopg://enterpriseflow:local-demo-db-password@localhost:5432/enterpriseflow'
export REDIS_URL='redis://localhost:6379/0'
export S3_ENDPOINT_URL='http://localhost:9000'
export OIDC_TOKEN_URL='http://localhost:8080/realms/enterpriseflow/protocol/openid-connect/token'
export OIDC_JWKS_URL='http://localhost:8080/realms/enterpriseflow/protocol/openid-connect/certs'
.venv/bin/uvicorn app.main:app --reload --no-access-log
```

Run migrations first with `make migrate`. In another terminal start `.venv/bin/celery -A app.worker.celery_app worker --loglevel=INFO`; set the same host overrides there. Start the frontend with `cd apps/web && npm run dev`. Tests can use their own SQLite fixtures, but PostgreSQL integration tests are needed to verify pgvector and RLS.

## Integration checks

`make test-e2e` runs browser tests with explicit API fixtures. After `make dev` and `make seed`, `make test-e2e-live` runs the separate suite through real Keycloak sessions, the API, PostgreSQL, background workers and object storage. Keep provider keys empty for this suite's missing-provider check. It uses only the documented synthetic accounts and creates clearly labeled test records. See `apps/web/README.md` for browser installation and environment overrides.

For database isolation and concurrent approval tests, create a **disposable PostgreSQL database** on a server with pgvector. Set both `DATABASE_URL` and `TEST_DATABASE_URL` to its admin connection using the `postgresql+psycopg` scheme; these tests create temporary restricted roles. Use `APP_ENV=test` and `STORAGE_BACKEND=local`, then run:

```sh
(cd apps/api && ../../.venv/bin/alembic upgrade head)
make test-postgres
```

Migration reversibility can be checked by running `alembic downgrade base` followed by `alembic upgrade head` in that disposable database. Never run the downgrade against the populated application database. The integration tests clean up their own records; remove only the disposable database after finishing.

## Ingestion safety

Development records structural validation when no antivirus service is configured. Production must set `REQUIRE_VIRUS_SCAN=true` and provide `CLAMAV_HOST`/`CLAMAV_PORT` for a maintained private ClamAV daemon. Unavailable mandatory scanning must fail closed. For local scanner testing, run `docker compose --profile antivirus up -d clamav`, set `CLAMAV_HOST=clamav` and `REQUIRE_VIRUS_SCAN=true` in `.env`, then recreate the backend/worker. Initial signature download can take several minutes and needs additional memory. The optional official ClamAV image manages its local signatures; a production scanner service and its operations remain external deployment prerequisites.

## Troubleshooting

- `docker info` fails: start Docker Desktop or your configured container runtime before `make dev`.
- API is up but login fails: inspect `docker compose logs keycloak`; check issuer, public API URL and redirect URI.
- New realm fixture changes do not appear: import does not overwrite an existing realm. Use the Keycloak admin UI to inspect and deliberately update development identity state.
- Login reports an invalid identity token on an older local realm: under Clients → enterpriseflow-web → Client scopes, assign `basic` as a Default scope. Keycloak's `basic` scope supplies the required `sub` subject claim. The current realm fixture includes it; existing realms require this update because imports do not overwrite them. Keep JWT subject validation enabled. See the [Keycloak client-scope documentation](https://www.keycloak.org/docs/26.5.7/server_admin/index.html).
- An older realm can also omit the required API audience. Under Clients → enterpriseflow-web → Client scopes → enterpriseflow-web-dedicated → api-audience, clear Included Client Audience, set Included Custom Audience to `enterpriseflow-api`, enable Add to access token, disable Add to ID token, and save. The API is a custom audience rather than a separate Keycloak client. Keep JWT audience validation enabled.
- AI action reports unavailable: configure a supported provider key and restart backend and worker.
- PostgreSQL access denied: migrations must use the privileged migration service; the normal app login cannot create tables or bypass RLS.
- Images build for the wrong CPU: publish AWS images with `--platform linux/amd64`, matching the task definitions.
- Shared API image tag errors with Docker's classic builder: use `make build`, then `docker compose up --no-build --wait`. The build target selects one service for each image.
