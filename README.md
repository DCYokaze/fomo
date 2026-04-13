# Game Monitor

Gamer-for-hire platform. Real-time account monitoring for hirers.

## Structure

    game-monitor/
    ├── server/              FastAPI backend
    │   ├── main.py          All API endpoints
    │   ├── requirements.txt
    │   ├── Dockerfile
    │   ├── .env.example     Safe to push — no real values
    │   └── static/
    │       ├── hunter/      Hunter dashboard (copy from client-hunter/)
    │       └── payer/       Payer dashboard (copy from client-payer/)
    ├── client-hunter/
    │   └── index.html       Hunter React app
    ├── client-payer/
    │   └── index.html       Payer React app
    ├── DEPLOY.md            Full GCP deployment guide
    └── README.md

## Database

Neon (free PostgreSQL) — https://neon.tech
Connection via single DATABASE_URL environment variable.
No Cloud SQL needed. Cost: $0/month on free tier.

## Roles & API Keys

| Role     | Env var           | Can access |
|----------|-------------------|------------|
| Hunter   | HUNTER_API_KEYS   | /hunter/*  |
| Payer    | PAYER_API_KEYS    | /payer/*   |
| Tray app | TRAY_API_KEYS     | /heartbeat |

## Endpoints

### Tray App (future)
- POST /heartbeat

### Hunter
- GET  /hunter/jobs
- GET  /hunter/my-jobs/{hunter_id}
- POST /hunter/jobs/{id}/accept
- POST /hunter/jobs/{id}/complete

### Payer
- GET  /payer/status/{account_id}
- GET  /payer/history/{account_id}
- POST /payer/jobs

## Run locally

    cd server
    cp .env.example .env
    # Fill in DATABASE_URL from neon.tech
    pip install -r requirements.txt
    uvicorn main:app --reload

    # Open in browser:
    # Hunter: http://localhost:8000/hunter/
    # Payer:  http://localhost:8000/payer/

## Deploy

See DEPLOY.md — 9 steps, ~$0/month.
