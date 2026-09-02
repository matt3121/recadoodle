# Recadoodle

An experimental, unofficial Python/Flask replacement backend for preserved April 2023
Rec Room clients (`20230414`). Not affiliated with or endorsed by Rec Room Inc.
Compatibility with other builds is not guaranteed.

## important read me : 
just before you begin the deployment process please keep in mind this server is not meant to be used for communities as it lacks security and is intended for experimentation.
please feel free to join the discord for any news on updates and help : 
recadoodle discord - https://discord.gg/guazzTRvnk 


## Features

- Password accounts, developer roles, token authentication and a password-required account picker.
- Personal dorms, room discovery, room saves, circuit values and room thumbnails.
- Avatar/equipment catalogs, outfits, friends, chat and WebSocket notifications.
- Experimental clubs, events, reports and other protocol endpoints; some remain stubs.
- Database readiness monitoring at `/readyz`, with HTTP 503 when the database is unavailable.

These endpoints do not guarantee every feature works in-game. This is not a hardened,
production-ready public service. Use a small, controlled test deployment first.

## Quick start (Windows, local testing)

Install Python 3.12. In this folder:

```powershell
Copy-Item .env.example .env
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe manage.py create-developer --username YOUR_USERNAME
.\.venv\Scripts\python.exe serve.py
```

The password is entered privately at the prompt. Coach occupies ID 1; the first developer
on an empty database normally receives ID 2. No SQLite account or cloud database signup
is required. SQLite stores local data under `instance/`.

Visit `http://localhost:5000/healthz` to check the API. `serve.py` is a local development
server, not the recommended public deployment. See [DEPLOYMENT.md](DEPLOYMENT.md) for
Docker, Cloudflare Tunnel, Photon settings, client setup and troubleshooting.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## Privacy and security

Never upload `.env`, `instance/`, client logs, local patch configs or backups. The Git and
Docker ignore files exclude these. Use a unique JWT secret, strong passwords and HTTPS.
No default developer credentials are provided. Keep passwordless login disabled.
The cached-platform association only selects an account; it does not authenticate it.
Client debug HTTP logging can expose passwords and tokens: leave it off.

WebSocket connection state and rate limits are process-local, so the supplied deployment
uses one worker. Do not increase replicas/workers without shared state support.

## Attribution

Required third-party MIT notices are retained in `LICENSE` and
`rrserver/data/THIRD-PARTY-LICENSE`. Catalog identifiers and game-related
assets do not imply ownership of Rec Room trademarks or a license to distribute its client.
No client patch, reference checkout, game executable, generated interop assembly, or private server dataset is included.
