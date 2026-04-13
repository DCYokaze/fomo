# GCP Cloud Run — Deployment Manual
# Game Monitor Platform (Neon DB — Free PostgreSQL)
# ─────────────────────────────────────────────────────────────

## Overview

One container on Cloud Run + Neon (free PostgreSQL, no Cloud SQL needed).

    https://your-app.run.app/hunter/   ← Hunter dashboard
    https://your-app.run.app/payer/    ← Payer dashboard
    https://your-app.run.app/hunter/*  ← Hunter API
    https://your-app.run.app/payer/*   ← Payer API
    https://your-app.run.app/heartbeat ← Tray app

Cost: ~$0/month
  - Cloud Run: free tier (scales to zero)
  - Neon PostgreSQL: free tier (0.5GB, no credit card)
  - Secret Manager: free at low volume
  - Cloud Build: free (120 min/day)


## Final folder structure before deploy

    hunter_x_payer/
    ├── main.py
    ├── requirements.txt
    ├── Dockerfile
    ├── docker-compose.yml
    ├── .gitignore
    ├── .env.example           ← safe to push to GitHub
    └── static/
        ├── hunter/
        │   └── index.html
        └── payer/
            └── index.html


## Prerequisites — install these first

1. Google Cloud SDK
   https://cloud.google.com/sdk/docs/install

2. Docker Desktop (optional — we use Cloud Build)
   https://www.docker.com/products/docker-desktop

   Verify:
       gcloud --version


═══════════════════════════════════════════════════════════════
STEP 1 — CREATE FREE NEON DATABASE
═══════════════════════════════════════════════════════════════

1. Go to https://neon.tech and sign up (free, no credit card)

2. Create a new project:
   - Name: game-monitor
   - Region: AWS ap-southeast-1 (Singapore — closest to Bangkok)
   - PostgreSQL version: 16

3. Create a database:
   - Click "Databases" → "New Database"
   - Name: monitor

4. Get your connection string:
   - Click "Dashboard" → "Connection Details"
   - Select database: monitor
   - Copy the connection string — looks like:
     postgresql://user:pass@ep-xxx.ap-southeast-1.aws.neon.tech/monitor?sslmode=require

5. Save this string — you will use it in Step 3 below.

Note: Neon's free tier pauses after 5 minutes of inactivity.
On first request after a pause, there is a ~1 second cold start.
This is fine for beta. Paid tier ($19/month) removes the pause.


═══════════════════════════════════════════════════════════════
STEP 2 — GCP PROJECT SETUP
═══════════════════════════════════════════════════════════════

    # Login to GCP
    gcloud auth login

    # Create project (skip if you have one already)
    gcloud projects create game-monitor-prod --name="Game Monitor"

    # Set as active project
    gcloud config set project game-monitor-prod

    # Link billing account (required even for free tier Cloud Run)
    # Do this at: https://console.cloud.google.com/billing
    # You will NOT be charged unless you exceed free tier limits.

    # Enable required APIs
    gcloud services enable run.googleapis.com
    gcloud services enable secretmanager.googleapis.com
    gcloud services enable cloudbuild.googleapis.com
    gcloud services enable containerregistry.googleapis.com


═══════════════════════════════════════════════════════════════
STEP 3 — STORE SECRETS IN SECRET MANAGER
═══════════════════════════════════════════════════════════════

    # Neon database URL (from Step 1)
    echo -n "postgresql://user:pass@ep-xxx.ap-southeast-1.aws.neon.tech/monitor?sslmode=require" | \
      gcloud secrets create database-url \
        --replication-policy=automatic \
        --data-file=-

    # Hunter API keys (comma separated — one per hunter if you want)
    echo -n "hunter-key-abc123" | \
      gcloud secrets create hunter-api-keys \
        --replication-policy=automatic \
        --data-file=-

    # Payer API keys
    echo -n "payer-key-xyz789" | \
      gcloud secrets create payer-api-keys \
        --replication-policy=automatic \
        --data-file=-

    # Tray app keys
    echo -n "tray-key-tbd111" | \
      gcloud secrets create tray-api-keys \
        --replication-policy=automatic \
        --data-file=-

    # Verify
    gcloud secrets list


═══════════════════════════════════════════════════════════════
STEP 4 — PREPARE LOCAL FILES
═══════════════════════════════════════════════════════════════

    # From repo root — static files are already in place.
    # No copying needed.

    # IMPORTANT: Update API_BASE in both HTML files
    # Open static/hunter/index.html — find this line near the top of <script>:
    #   const API_BASE = "http://localhost:8000";
    # Change to:
    #   const API_BASE = "";
    #
    # Do the same in static/payer/index.html
    #
    # Empty string = same origin = no CORS issues

    # Also update the hardcoded API keys in each HTML file
    # to match what you stored in Secret Manager above:
    #   const HUNTER_KEY = "hunter-key-abc123";
    #   const PAYER_KEY  = "payer-key-xyz789";


═══════════════════════════════════════════════════════════════
STEP 5 — BUILD DOCKER IMAGE
═══════════════════════════════════════════════════════════════

    # From repo root

    # Build via Cloud Build (runs in GCP, no local Docker needed)
    gcloud builds submit \
      --tag gcr.io/game-monitor-prod/game-monitor \
      .

    # Takes ~2-3 minutes first time.
    # Verify:
    gcloud container images list \
      --repository=gcr.io/game-monitor-prod


═══════════════════════════════════════════════════════════════
STEP 6 — DEPLOY TO CLOUD RUN
═══════════════════════════════════════════════════════════════

    # NOTE: No --add-cloudsql-instances needed anymore.
    # Neon is a regular external PostgreSQL — connects over HTTPS.

    gcloud run deploy game-monitor \
      --image gcr.io/game-monitor-prod/game-monitor \
      --platform managed \
      --region asia-southeast1 \
      --allow-unauthenticated \
      --memory 512Mi \
      --cpu 1 \
      --min-instances 0 \
      --max-instances 3 \
      --set-secrets \
        DATABASE_URL=database-url:latest,\
        HUNTER_API_KEYS=hunter-api-keys:latest,\
        PAYER_API_KEYS=payer-api-keys:latest,\
        TRAY_API_KEYS=tray-api-keys:latest

    # After deploy, GCP prints your URL:
    # Service URL: https://game-monitor-XXXXX-as.a.run.app
    # Save this URL.


═══════════════════════════════════════════════════════════════
STEP 7 — GRANT SECRET MANAGER ACCESS
═══════════════════════════════════════════════════════════════

    # Get your project number
    PROJECT_NUMBER=$(gcloud projects describe game-monitor-prod \
      --format="value(projectNumber)")

    # Default Cloud Run service account
    SERVICE_ACCOUNT="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

    # Grant access to each secret
    for SECRET in database-url hunter-api-keys payer-api-keys tray-api-keys; do
      gcloud secrets add-iam-policy-binding $SECRET \
        --member="serviceAccount:${SERVICE_ACCOUNT}" \
        --role="roles/secretmanager.secretAccessor"
    done

    # Redeploy once to pick up permissions
    gcloud run services update game-monitor \
      --region asia-southeast1


═══════════════════════════════════════════════════════════════
STEP 8 — TEST EVERYTHING
═══════════════════════════════════════════════════════════════

Replace YOUR_URL with your actual Cloud Run URL.

    # Simulate a heartbeat (replaces tray app for now)
    curl -X POST https://YOUR_URL/heartbeat \
      -H "x-api-key: tray-key-tbd111" \
      -H "Content-Type: application/json" \
      -d '{"account_id":"player_a","game":"BDO","status":"active"}'

    # Expected: {"ok": true}

    # Test payer status — should now show "active"
    curl https://YOUR_URL/payer/status/player_a \
      -H "x-api-key: payer-key-xyz789"

    # Test hunter jobs list
    curl https://YOUR_URL/hunter/jobs \
      -H "x-api-key: hunter-key-abc123"

    # Open dashboards in browser
    # Hunter: https://YOUR_URL/hunter/
    # Payer:  https://YOUR_URL/payer/


═══════════════════════════════════════════════════════════════
STEP 9 — REDEPLOY AFTER CODE CHANGES
═══════════════════════════════════════════════════════════════

    # From repo root

    gcloud builds submit \
      --tag gcr.io/game-monitor-prod/game-monitor \
      . && \
    gcloud run deploy game-monitor \
      --image gcr.io/game-monitor-prod/game-monitor \
      --region asia-southeast1

    # Zero downtime rolling update. Takes ~2-3 minutes.


═══════════════════════════════════════════════════════════════
UPDATING A SECRET VALUE LATER
═══════════════════════════════════════════════════════════════

    # Add a new hunter key (keep old ones, add new version)
    echo -n "hunter-key-abc123,hunter-key-new456" | \
      gcloud secrets versions add hunter-api-keys --data-file=-

    # Cloud Run picks up :latest automatically on next deploy.
    # To pick up immediately without redeploy:
    gcloud run services update game-monitor --region asia-southeast1


═══════════════════════════════════════════════════════════════
SECURITY CHECKLIST
═══════════════════════════════════════════════════════════════

    [ ] .env is in .gitignore — never pushed to GitHub
    [ ] .env.example pushed instead (empty values only)
    [ ] DATABASE_URL stored in Secret Manager, not env vars
    [ ] Neon connection string uses ?sslmode=require (encrypted)
    [ ] Separate API keys for hunters, payers, tray app
    [ ] Container runs as non-root (appuser in Dockerfile)
    [ ] HTTPS enforced automatically by Cloud Run
    [ ] CORS tightened to your Cloud Run URL after first deploy:
        In main.py: allow_origins=["https://YOUR_URL.run.app"]
        Then redeploy.


═══════════════════════════════════════════════════════════════
COMMON ERRORS
═══════════════════════════════════════════════════════════════

    Error: could not connect to server (Neon)
    Fix:  Check DATABASE_URL has ?sslmode=require at the end
          Check the URL was copied fully from Neon dashboard
          Neon free tier pauses — first request after pause may be slow

    Error: permission denied on secret
    Fix:  Re-run Step 7

    Error: 404 on /hunter/ or /payer/
    Fix:  Check static/hunter/index.html and static/payer/index.html exist
          Run: find . -name index.html

    Error: 401 Unauthorized
    Fix:  Header name must be exactly: x-api-key (lowercase)
          Value must match what is stored in Secret Manager

    Error: container fails to start
    Fix:  gcloud run logs read game-monitor --region asia-southeast1


═══════════════════════════════════════════════════════════════
COST SUMMARY
═══════════════════════════════════════════════════════════════

    Neon PostgreSQL    Free tier (0.5GB, pauses when idle)   $0/month
    Cloud Run          Free tier (2M req/month, scales to 0) $0/month
    Secret Manager     Free at low volume                    $0/month
    Cloud Build        Free (120 min/day)                    $0/month
    ──────────────────────────────────────────────────────────────────
    Total                                                    $0/month

    When to upgrade:
    - Neon paid ($19/mo): when you need always-on DB (no cold start)
    - Cloud SQL ($12/mo): when you need GCP-native SLA and private IP
    Both are easy migrations — same PostgreSQL, same code, just swap DATABASE_URL.


═══════════════════════════════════════════════════════════════
USEFUL COMMANDS
═══════════════════════════════════════════════════════════════

    # View live logs
    gcloud run logs tail game-monitor --region asia-southeast1

    # View recent logs
    gcloud run logs read game-monitor --region asia-southeast1 --limit 50

    # Get service URL
    gcloud run services describe game-monitor \
      --region asia-southeast1 \
      --format="value(status.url)"

    # List all secrets
    gcloud secrets list

    # View a secret value (careful — this prints it to terminal)
    gcloud secrets versions access latest --secret=database-url
