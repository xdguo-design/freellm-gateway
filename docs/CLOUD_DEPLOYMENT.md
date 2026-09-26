# Single-instance cloud deployment

This deployment profile is intentionally **single instance**. The current quota
reservation mechanism is process-local and the primary database is SQLite.
Run exactly one FreeLLM Gateway application replica until quota reservations and
usage persistence are moved to a shared transactional store.

## What is persisted

Mount a persistent volume at `/data`. The container stores:

- `/data/gateway.sqlite3` — providers, model routes, tenants, applications,
  quotas and usage.
- `/data/provider-secrets.json` — Provider API keys encrypted with Fernet.
- `/data/gateway-connections.jsonl` — safe connection/usage log.
- `/data/catalog-export.json` — generated public catalog export.

The encryption key is **not** stored in the volume. Keep
`FREELLM_GATEWAY_SECRET_KEY` in the cloud provider's secret manager or
environment-secret facility. A volume backup without that key cannot decrypt
Provider credentials.

## Required production environment

Copy `.env.cloud.example` to `.env.cloud` for local/VPS deployment. Generate
three independent secrets:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
python -c "import secrets; print(secrets.token_urlsafe(48))"
python -c "import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```

Use the first value for `FREELLM_GATEWAY_API_TOKEN`, the second for
`FREELLM_GATEWAY_ADMIN_TOKEN`, and the third for
`FREELLM_GATEWAY_SECRET_KEY`.

The production image sets `FREELLM_GATEWAY_REQUIRE_EXPLICIT_TOKENS=1`.
Startup fails instead of generating temporary credentials when API/Admin tokens
are missing. Likewise, configuring only one of
`FREELLM_GATEWAY_SECRETS_FILE` or `FREELLM_GATEWAY_SECRET_KEY` fails closed.

Important environment variables:

| Variable | Production value |
| --- | --- |
| `FREELLM_GATEWAY_API_TOKEN` | Long random token used by OpenAI-compatible clients |
| `FREELLM_GATEWAY_ADMIN_TOKEN` | Different long random token used by the remote admin UI/API |
| `FREELLM_GATEWAY_SECRET_KEY` | Fernet key kept in the cloud secret manager |
| `FREELLM_GATEWAY_SECRETS_FILE` | `/data/provider-secrets.json` |
| `FREELLM_GATEWAY_DB` | `/data/gateway.sqlite3` |
| `FREELLM_GATEWAY_CONNECTION_LOG` | `/data/gateway-connections.jsonl` |
| `FREELLM_GATEWAY_HOST` | `0.0.0.0` inside the container |
| `PORT` or `FREELLM_GATEWAY_PORT` | Cloud-assigned port or `8765` |
| `FREELLM_DOMAIN` | Public DNS name when using the included Caddy stack |

Do not put Provider API keys into the image, Dockerfile, repository, or compose
file. Add them through the admin UI after HTTPS is active; they are encrypted
before being written to the persistent volume. Application logs should be
collected from container stdout/stderr by the cloud logging service; the
connection/usage JSONL file remains on the persistent volume.

## Build and run the container

```bash
docker build -t freellm-gateway:local .
docker volume create freellm-gateway-data

docker run -d \
  --name freellm-gateway \
  --restart unless-stopped \
  --env-file .env.cloud \
  -v freellm-gateway-data:/data \
  -p 127.0.0.1:8765:8765 \
  freellm-gateway:local
```

The image runs as non-root UID/GID `10001`. A named Docker volume works
without extra ownership steps. If a host bind mount is used instead, make the
directory writable by UID 10001 before startup.

## Health checks

- `GET /health` is the lightweight liveness endpoint.
- `GET /health/ready` is the deployment readiness endpoint. It returns 200
  only when persistent SQLite access and secret storage are available.
- The Docker image's `HEALTHCHECK` calls `/health/ready`.

Example:

```bash
curl -fsS http://127.0.0.1:8765/health/ready
```

A cloud platform should use `/health/ready` for readiness/traffic routing and
`/health` for liveness when it supports separate probes.

## HTTPS option A: cloud-managed TLS

For Render, Railway, Fly.io, Azure Container Apps, Cloud Run-like platforms, or
another container platform with managed HTTPS, terminate TLS at the platform
edge and route traffic to the container's HTTP port. Do not expose a second
public HTTP endpoint around the platform proxy.

Configure:

1. exactly one application replica;
2. a persistent volume mounted at `/data`;
3. all required environment secrets;
4. readiness path `/health/ready`;
5. the platform-provided `PORT` if required;
6. HTTPS-only public ingress.

## WorkBuddy cloud deployment (CloudBase Run)

WorkBuddy can deploy this backend as a Docker/container service through
Tencent CloudBase Run. Use the repository Dockerfile and attach a persistent
Cloud File Storage (CFS) mount at `/data`; the container's writable layer is
ephemeral and must not hold the SQLite database or encrypted provider keys.

Configure the CloudBase service as follows:

1. Build from this repository with the root `Dockerfile`.
2. Mount a CFS file system at `/data`, in the service's supported region and
   network. Keep the SQLite database and encrypted credential file on this
   mount so they survive restarts and new container instances.
3. Set the service's maximum instance count to **1**. Do not enable autoscaling
   or deploy multiple active replicas: quota reservations are process-local
   and SQLite is the single-instance storage profile.
4. Add `FREELLM_GATEWAY_API_TOKEN`, `FREELLM_GATEWAY_ADMIN_TOKEN`, and
   `FREELLM_GATEWAY_SECRET_KEY` as CloudBase environment secrets. Also set
   `FREELLM_GATEWAY_DB=/data/gateway.sqlite3`,
   `FREELLM_GATEWAY_SECRETS_FILE=/data/provider-secrets.json`,
   `FREELLM_GATEWAY_CONNECTION_LOG=/data/gateway-connections.jsonl`, and
   `FREELLM_GATEWAY_HOST=0.0.0.0`. Use the port assigned by the service via
   `PORT` (or set `FREELLM_GATEWAY_PORT=8765` if configuring that port).
   Generate secrets as described above; never use the example placeholders.
5. Configure readiness to `GET /health/ready` and liveness to
   `GET /health`. Publish the admin UI at `/admin/` and the compatible API
   under `/v1` through the service's HTTPS endpoint.
6. Back up the complete mounted `/data` volume and the encryption key
   separately. Test restoring both before relying on the service.

Treat this as a single-instance deployment. Before increasing the instance
count, migrate quota reservations and persistent state to a shared
transactional database, then run the full release gate again.

## HTTPS option B: VPS with Caddy

Point the domain's A/AAAA DNS record at the server, allow inbound TCP 80/443
(and UDP 443 for HTTP/3), then:

```bash
cp .env.cloud.example .env.cloud
# edit .env.cloud and replace every REPLACE_* value

docker compose --env-file .env.cloud -f docker-compose.cloud.yml up -d --build
```

Caddy obtains and renews certificates automatically and proxies HTTPS traffic
to the private `gateway:8765` container. The Gateway container itself is not
published directly on the host in this stack.

Verify:

```bash
curl -fsS "https://$FREELLM_DOMAIN/health/ready"
```

The admin UI is then available at `https://$FREELLM_DOMAIN/admin/`. Remote
admin API calls require `Authorization: Bearer <FREELLM_GATEWAY_ADMIN_TOKEN>`;
normal OpenAI-compatible client calls under `/v1` use
`FREELLM_GATEWAY_API_TOKEN` or an application key.

## Backup and restore

For the first single-instance release, take a consistent volume backup while
the Gateway container is stopped. Back up the entire `/data` volume and keep a
separate protected copy of `FREELLM_GATEWAY_SECRET_KEY`.

A restore requires both:

1. the persistent `/data` contents;
2. the exact encryption key used to create `provider-secrets.json`.

Changing the encryption key without re-encrypting stored credentials makes
existing Provider credentials unreadable.

## Scaling boundary

Do **not** enable autoscaling, multiple replicas, active-active regions, or
multiple containers sharing the same SQLite file. The in-flight quota
reservation map is process-local, so multiple replicas could independently
accept requests against the same remaining quota.

The next scaling step is to move database/usage/quota reservations to a shared
transactional backend before increasing replicas.
