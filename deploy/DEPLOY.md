# Lakshmi — Self-hosted deployment (VPS backend + Netlify frontend)

Two-origin production setup:

- **Backend** — Docker on your VPS behind your existing nginx.
  URL: `https://sms.saisanathana.com`
- **Frontend** — Netlify, built from GitHub.
  URL: `https://<your-site>.netlify.app`

Everything below assumes the repo is already on GitHub.

---

## 1. VPS prerequisites

Ubuntu 22.04/24.04 with these already in place:

- `docker` + `docker compose` v2 → `sudo apt install docker.io docker-compose-plugin`
- `nginx` (you already have this)
- `certbot` with the nginx plugin → `sudo apt install certbot python3-certbot-nginx`
  (skip if you already provision certs for other sites the same way)

Point DNS **before** running certbot:

    sms.saisanathana.com  A  <VPS public IPv4>

Wait ~1 minute for propagation (`dig +short sms.saisanathana.com`).

---

## 2. Backend

    # 2a. Clone
    sudo mkdir -p /opt/lakshmi && sudo chown $USER: /opt/lakshmi
    git clone <your-github-repo> /opt/lakshmi
    cd /opt/lakshmi/deploy

    # 2b. Config — copy the template and fill in the blanks
    cp .env.production.example .env.production
    nano .env.production            # set JWT_SECRET, ADMIN_PASSWORD, RESEND_API_KEY, CORS_ORIGINS, APP_URL

    # 2c. Upload directory (bind-mounted into the container)
    mkdir -p data/uploads

    # 2d. Bring it up
    docker compose --env-file .env.production up -d --build

    # Backend is now reachable at http://127.0.0.1:8001 on the VPS ONLY.
    curl -fsS http://127.0.0.1:8001/api/    # -> {"message":"Dance Billing API"}

Generate a `JWT_SECRET` if you don't have one:

    python3 -c "import secrets; print(secrets.token_hex(32))"

---

## 3. nginx + TLS

    sudo cp /opt/lakshmi/deploy/nginx-lakshmi.conf \
            /etc/nginx/sites-available/sms.saisanathana.com
    sudo ln -s /etc/nginx/sites-available/sms.saisanathana.com \
               /etc/nginx/sites-enabled/
    sudo nginx -t && sudo systemctl reload nginx

    sudo certbot --nginx -d sms.saisanathana.com

Certbot rewrites the server block with the correct `ssl_certificate` paths and
sets up auto-renewal via its systemd timer.

Test:

    curl -sI https://sms.saisanathana.com/api/    # expect 200 with "content-type: application/json"

---

## 4. Netlify

1. Log in to Netlify → **Add new site → Import an existing project → GitHub**
   → pick this repo, main branch.
2. Netlify auto-detects `netlify.toml` at repo root — build settings should
   already be filled in (`base=frontend`, `command=yarn install --frozen-lockfile && yarn build`,
   `publish=build`).
3. **Site settings → Environment variables** → add:

        REACT_APP_BACKEND_URL = https://sms.saisanathana.com

4. Click **Deploy site**. First build takes ~2 min. Take note of the assigned
   URL, e.g. `https://tender-fudge-1a2b3c.netlify.app`.

5. Go back to `/opt/lakshmi/deploy/.env.production` and set:

        CORS_ORIGINS = https://tender-fudge-1a2b3c.netlify.app
        APP_URL      = https://tender-fudge-1a2b3c.netlify.app

   Then restart the backend to pick up the new env:

        cd /opt/lakshmi/deploy
        docker compose --env-file .env.production up -d backend

---

## 5. First login

Visit the Netlify URL → log in with `ADMIN_EMAIL` / `ADMIN_PASSWORD` from
`.env.production`. The admin document is auto-seeded on first startup.

---

## 6. Upgrading later

    cd /opt/lakshmi
    git pull
    cd deploy
    docker compose --env-file .env.production build backend
    docker compose --env-file .env.production up -d backend
    docker compose logs -f --tail=50 backend        # watch it come up

Nginx and mongo don't need to restart for a code-only change.

---

## 7. Backups (recommended)

Cron-style dump of Mongo to a timestamped file, kept for 14 days:

    # crontab -e
    5 3 * * *   cd /opt/lakshmi/deploy && \
                docker compose exec -T mongo mongodump --archive --gzip \
                  > /opt/lakshmi/backups/$(date +\%Y\%m\%d).mongo.gz && \
                find /opt/lakshmi/backups -mtime +14 -delete

Uploaded photos live in `/opt/lakshmi/deploy/data/uploads/` — back that
directory up the same way (rsync, restic, borg — your call).

---

## 8. Troubleshooting

| Symptom | Likely cause / fix |
| --- | --- |
| Netlify → API returns CORS error | `CORS_ORIGINS` in `.env.production` is missing the exact Netlify origin. No trailing slash. Restart backend after editing. |
| Login works then every action returns 401 | Cookies blocked by browser third-party rules. The `Bearer` token fallback kicks in automatically — check `Authorization` header in the Network tab. |
| `/api/uploads/photo` returns 500 | `data/uploads/` directory isn't writable by the container user. `sudo chown -R 1000:1000 data/uploads`. |
| Reset password email never arrives | Check `docker compose logs backend` — if you left `RESEND_API_KEY` blank the link is only logged, never emailed. |
| certbot fails | DNS hasn't propagated yet, or another site is already using port 80. `sudo lsof -i :80` |
