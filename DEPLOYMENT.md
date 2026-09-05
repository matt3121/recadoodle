# Deploy your own Recadoodle server

## 1. Download and configure

Clone this repository or download and extract its ZIP. Install Docker with Compose
(Docker Desktop in Linux-container mode on Windows). Copy `.env.example` to `.env`.
Edit the private `.env` with your own values:

```dotenv
RECNET_DOMAIN=play.YOUR_DOMAIN
SINGLE_HOST_MODE=true
JWT_SECRET=PUT_A_RANDOM_SECRET_OF_AT_LEAST_32_CHARACTERS_HERE
PHOTON_REALTIME_APP_ID=PUT_YOUR_REALTIME_APP_ID_HERE
PHOTON_VOICE_APP_ID=PUT_YOUR_VOICE_APP_ID_HERE
PHOTON_CHAT_APP_ID=
PHOTON_REGION=us
SESSION_COOKIE_SECURE=true
TRUST_CLOUDFLARE_PROXY=true
TRUSTED_HOSTS=play.YOUR_DOMAIN,localhost,127.0.0.1
CLOUDFLARE_TUNNEL_TOKEN=PUT_YOUR_TUNNEL_TOKEN_HERE
ALLOW_PASSWORDLESS_ACCOUNTS=false
CREATE_DEVELOPER_ACCOUNTS_ON_LOGIN=false
```

Replace every placeholder. `RECNET_DOMAIN` is a hostname without `https://` or a path.
Generate a secret locally with `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
Do not post the result or reuse a sample password. Changing JWT_SECRET invalidates sessions.
Create your own Photon Realtime and Voice apps; use matching IDs in the client patch.
Photon traffic is separate from the HTTP tunnel. A tunnel does not provide Photon hosting.
Keep `CREATE_DEVELOPER_ACCOUNTS_ON_LOGIN=false` on an Internet-accessible server. Enabling it
allows any new in-game account to receive developer and moderator privileges.

## 2. Start the backend and create your account

```console
docker compose up -d --build backend
docker compose exec backend python manage.py create-developer --username YOUR_USERNAME
```

Enter a unique password of at least 12 characters twice. Record the printed account ID.
Coach remains a system account and has no published password. Do not attempt to use it.
Persistent data is stored in the `recnet-data` Docker volume.

## 3. Set up Cloudflare Tunnel

In your Cloudflare account, create a Cloudflared tunnel for a domain you control. Save
its tunnel token in your local `.env`. Add a published application route:

- Public hostname: the same hostname used in `RECNET_DOMAIN`.
- Service type: HTTP.
- Service URL: `backend:5000` (equivalently `http://backend:5000` when the UI accepts a full URL).

Both containers share the Compose network. Do **not** use `localhost:5000` for the origin
inside the Cloudflared container: that would point at Cloudflared itself.
Then start the connector:

```console
docker compose --profile tunnel up -d --build
docker compose logs --tail 50 backend cloudflared
```

Check `https://play.YOUR_DOMAIN/healthz` for `status: ok`, and `/` for JSON service URLs.
All discovered services should point to your hostname. No separate website is included.
Do not put browser-interactive Cloudflare Access login or challenge pages in front of the
game API; the game cannot complete them. Use appropriate network restrictions and API
rate limits instead. Only trust forwarded headers when access is through your trusted proxy.
The supplied port mapping is loopback-only; do not expose the Flask port directly.

Official references: [Cloudflare Tunnel setup](https://developers.cloudflare.com/tunnel/setup/)
and [Flask-Sock supported servers](https://flask-sock.readthedocs.io/en/latest/web_servers.html).
The supplied Gunicorn settings use one threaded worker for process-local notifications.

## 4. Configure the client

Use a legally obtained, compatible April 2023 client and a separately obtained compatible
client configuration method. This repository provides only the backend: no client patch,
patch source, game binaries, or generated game assemblies are included.
Set its nameserver to `https://play.YOUR_DOMAIN`, and set your own Photon IDs. Leave debug
logging off. Back up your client before modifying it. Never use a modified client with
the official live service or your normal online installation.

### Loading bar tries to create an account

Some clients request an empty-password account before showing a login screen. This server
rejects that intentionally. Create your account using the command above, then associate
your own platform identity with the password-required picker:

```console
docker compose exec backend python manage.py link-platform --account-id YOUR_ACCOUNT_ID --platform 0 --platform-id YOUR_STEAM_ID64
```

`0` is Steam. Use your own identity, not somebody else's. Restart the client. It should
offer the existing account and require its password. This association is not Steam ticket
verification and must never be treated as proof of identity. No IDs are pre-linked.

## 5. Backups, updates and troubleshooting

### Database readiness

`GET /readyz` executes a lightweight database query and returns HTTP 200 with
`{"status":"ready","checks":{"database":"ok"}}` when it succeeds. Database connection
or query errors return HTTP 503 with `database: unavailable`, without exposing error details.
Responses are not cached. Use this endpoint for database-readiness monitoring; `/healthz`
remains the process-liveness check. Readiness does not test Photon, room assets, database
writes or full gameplay compatibility.

Back up the persistent volume and your private `.env` securely before updates. Stop the
backend before taking a raw filesystem copy of SQLite. Alternatively, create a consistent
online backup while the server is running with the built-in SQLite backup command:

```console
docker compose exec backend python manage.py backup-database
docker compose exec backend ls -lh /app/instance/backups
docker compose cp backend:/app/instance/backups/recadoodle-YYYYMMDD-HHMMSS.sqlite3 .
```

The command uses SQLite's online backup API, verifies the new file with `quick_check`, and
refuses to overwrite an existing file. Backups default to `/app/instance/backups` in the
persistent volume. Use `--output /app/instance/backups/NAME.sqlite3` to choose a name.
Copy completed backups off the server and protect them like the live database: they contain
accounts and authentication data. Never commit backups. `docker compose down` preserves the
volume; **do not use `down -v`** unless you intend to erase all accounts, uploads and saves.

After pulling reviewed updates: `docker compose --profile tunnel up -d --build`.
For a restart: `docker compose restart backend`.

- 502: inspect backend/connector logs and confirm the origin is `backend:5000`.
- JSON discovery has the wrong host: fix `.env`, then recreate the containers.
- Login fails: check `instance/access.log` inside the volume for safe `AUTH rejected`
  categories. Do not enable raw request-body logging or share tokens.
- Version mismatch: use the intended client; newer builds are not supported by this patch.
- Rooms/voice fail: check Photon IDs, region, client compatibility and room assets separately.
- No HTML page: expected. Use `/healthz` and `/api/discovery`.

Do not assume endpoint tests prove in-game compatibility. Test with one client before
inviting others. No authentication, external account or domain from the original deployment
is needed or provided.
