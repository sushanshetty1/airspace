# Deploy

`docker-compose.prod.yml` runs three containers:

| Service | Image | Role |
| --- | --- | --- |
| `falkordb` | `falkordb/falkordb:6.0.2` | The graph. Data lives in the `falkordb-data` volume. |
| `api` | built from `server/` | `airspace serve` on port 8787, inside the network only. On start it indexes the bundled demo repository (`/data/repo`, a copy of `server/tests/fixtures/blog`) once FalkorDB answers. |
| `web` | built from `web/` | Caddy serves the site and Tower, and proxies `/api/*` to `api:8787`. Certificates live in the `caddy-data` volume. |

Only `web` publishes ports. FalkorDB and the API are not reachable from outside.

## Run it locally

```sh
docker compose -f docker-compose.prod.yml up -d --build
```

Open <http://localhost:8080> for the site and <http://localhost:8080/tower> for Tower.

Logs and status:

```sh
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs -f api
```

Stop it with `docker compose -f docker-compose.prod.yml down`. Add `-v` to delete the graph and the certificates as well.

## Run it on a VPS with a domain

1. Point an `A` (and `AAAA`, if the server has IPv6) record for the domain at the server.
2. Open ports 80 and 443 (TCP, and UDP 443 for HTTP/3) in the server's firewall. On Ubuntu with ufw:

   ```sh
   sudo ufw allow 80/tcp
   sudo ufw allow 443/tcp
   sudo ufw allow 443/udp
   ```

3. Install Docker Engine with the Compose plugin, clone the repository and create `.env` next to `docker-compose.prod.yml`:

   ```sh
   DOMAIN=airspace.example.com
   HTTP_PORT=80
   HTTPS_PORT=443
   ```

4. Start the stack:

   ```sh
   docker compose -f docker-compose.prod.yml up -d --build
   ```

With `DOMAIN` set, Caddy gets a certificate from Let's Encrypt on the first request, serves HTTPS on 443 and redirects HTTP to HTTPS. Without it, Caddy serves plain HTTP on port 80 of the container (published on `HTTP_PORT`, 8080 by default).

## Run it behind an existing Traefik

If another proxy already owns ports 80 and 443 (Dokploy's Traefik, for example), add `docker-compose.traefik.yml`. The web container then publishes no ports. Traefik routes `DOMAIN` to it over its own network and gets the certificate.

```sh
# .env
DOMAIN=airspace.example.com
# TRAEFIK_NETWORK=dokploy-network        (the network Traefik watches)
# TRAEFIK_CERT_RESOLVER=letsencrypt      (the certificate resolver in Traefik's config)

docker compose -f docker-compose.prod.yml -f docker-compose.traefik.yml up -d --build
```

The HTTP router uses Traefik's `redirect-to-https@file` middleware, which Dokploy defines. Point the domain's DNS at the server before the first start, so the certificate request succeeds.

## Update

```sh
git pull
docker compose -f docker-compose.prod.yml up -d --build
```

Compose rebuilds the changed images and recreates only those containers. The graph and the certificates are kept in their volumes. The API re-indexes the demo repository on every start; indexing is idempotent.

To clear old images afterwards: `docker image prune -f`.

## Settings

| Variable | Default | Effect |
| --- | --- | --- |
| `DOMAIN` | unset | Site address. Set it to a domain name for automatic HTTPS. |
| `HTTP_PORT` | `8080` | Host port for HTTP. |
| `HTTPS_PORT` | `8443` | Host port for HTTPS (TCP and UDP). |
