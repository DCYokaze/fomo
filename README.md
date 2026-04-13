# Game Monitor

Gamer-for-hire platform. Real-time account monitoring for hirers.

## Structure

    hunter_x_payer/
    ├── main.py              All API endpoints (FastAPI)
    ├── requirements.txt
    ├── Dockerfile
    ├── docker-compose.yml
    ├── .env.example         Safe to push — no real values
    ├── static/
    │   ├── hunter/          Hunter dashboard
    │   │   └── index.html
    │   └── payer/           Payer dashboard
    │       └── index.html
    ├── DEPLOY.md            Full GCP deployment guide
    └── README.md

## Database

Neon (free PostgreSQL) — https://neon.tech
Connection via single DATABASE_URL environment variable.
No Cloud SQL needed. Cost: $0/month on free tier.

### Tables

| Table       | Description                                      |
|-------------|--------------------------------------------------|
| accounts    | Payer-owned game accounts                        |
| jobs        | Work requests (open → active → completed)        |
| heartbeats  | Online status pings from tray app                |
| games       | Supported game list (seeded on startup)          |

## Roles & API Keys

| Role     | Env var           | Can access              |
|----------|-------------------|-------------------------|
| Hunter   | HUNTER_API_KEYS   | /hunter/*               |
| Payer    | PAYER_API_KEYS    | /payer/*                |
| Tray app | TRAY_API_KEYS     | /heartbeat              |

## Endpoints

### Tray App
- `POST /heartbeat` — record online status ping for an account

### Hunter
- `GET  /hunter/jobs` — list all open jobs with latest heartbeat
- `GET  /hunter/my-jobs/{hunter_id}` — list jobs accepted by this hunter
- `POST /hunter/jobs/{id}/accept` — accept an open job (sets status → active)
- `POST /hunter/jobs/{id}/complete` — mark active job as completed
- `POST /hunter/jobs/{id}/progress` — update progress flag (`queued` or `in_progress`)
- `POST /hunter/jobs/{id}/working` — toggle working flag on/off

### Payer
- `GET  /payer/status/{account_id}` — latest heartbeat status for an account
- `GET  /payer/history/{account_id}` — last 50 heartbeat records
- `GET  /payer/jobs/{account_id}` — list jobs for an account (optional `?status=` filter)
- `POST /payer/jobs` — create a new job
- `DELETE /payer/jobs/{id}` — delete an open (not yet accepted) job
- `GET  /payer/games` — list available games

## Run locally

    cp .env.example .env
    # Fill in DATABASE_URL from neon.tech
    pip install -r requirements.txt
    uvicorn main:app --reload

    # Open in browser:
    # Hunter: http://localhost:8000/hunter/
    # Payer:  http://localhost:8000/payer/

## Deploy

See DEPLOY.md — 9 steps, ~$0/month.
