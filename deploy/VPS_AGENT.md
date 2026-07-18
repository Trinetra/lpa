# VPS Deployment — Agent Runbook

**Audience:** an autonomous coding agent (Claude Code / Cursor / similar) with shell access to the VPS.
**Goal:** deploy the Lakshmi Studio Ledger backend + MongoDB behind the host's existing nginx, terminated by Let's Encrypt.
**Total time when nothing goes wrong:** ~10 minutes.

---

## 0. Guardrails for the agent

- **Never proceed to the next phase until the verification command in the current phase returns the expected result.** Each phase has an explicit `# EXPECT:` comment.
- **Never overwrite `/etc/nginx/nginx.conf` or any file under `/etc/nginx/sites-available/` other than the one this runbook creates.** Other sites on this VPS must remain untouched.
- **Never commit `.env.production` to git.** It contains secrets.
- **If any command fails, stop and report to the user with the exact command, exit code, and last 20 lines of output.** Do not attempt creative recovery.
- All commands are idempotent — safe to re-run the whole document from the top if something fails.

---

## 1. Prerequisites the agent must confirm

Run this preflight block. If any check fails, stop and ask the user to fix it before proceeding.

```bash
# Preflight
set -e

# Must be Debian/Ubuntu family
[ -f /etc/debian_version ] || { echo "FAIL: not Debian/Ubuntu"; exit 1; }

# Docker + compose v2
docker --version && docker compose version   # EXPECT: both print a version

# nginx already installed and running
systemctl is-active nginx                    # EXPECT: active

# certbot with nginx plugin (install if missing)
which certbot || sudo apt-get update && sudo apt-get install -y certbot python3-certbot-nginx

# DNS points at this host
curl -sf https://ifconfig.me                 # note the IP → call this VPS_IP
dig +short sms.saisanathana.com              # EXPECT: same as VPS_IP
```

If `dig` returns nothing or a different IP, **stop** and tell the user to point the A record `sms.saisanathana.com → VPS_IP` and wait for propagation.

---

## 2. Secrets the agent must collect from the user

Prompt the user for the following values **before writing any file**. Store them in variables — do NOT echo them back to stdout in production; only redact confirmations.

| Variable | Format | Notes |
| --- | --- | --- |
| `GITHUB_REPO_URL` | `https://github.com/<owner>/<repo>.git` | Public or the agent has a PAT with read access |
| `ADMIN_PASSWORD` | ≥ 10 chars | This becomes the initial login password for user `lpathreya@gmail.com` |
| `RESEND_API_KEY` | `re_xxxxxxxxxxxxxxxxxxxx` | Optional — if the user hasn't created a Resend account yet, leave empty and note that email is disabled |
| `NETLIFY_URL` | `https://<slug>.netlify.app` or `""` | The frontend URL that will call this backend. If Netlify hasn't been set up yet, temporarily set to `""` and come back after Step 8 |

### Shortcut: source values from `deploy/.secrets.local` if it exists

The developer may have prefilled a git-ignored `deploy/.secrets.local` file in
the repo (e.g. containing `RESEND_API_KEY=re_...`). If present, source it
before prompting so those values don't need to be re-typed:

```bash
if [ -f /opt/lakshmi/deploy/.secrets.local ]; then
  set -a; . /opt/lakshmi/deploy/.secrets.local; set +a
  echo "Sourced $(basename $(pwd))/.secrets.local"
fi
```

Also compute (do not ask the user):

```bash
JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
```

---

## 3. Clone the repository

```bash
sudo mkdir -p /opt/lakshmi
sudo chown "$USER:$USER" /opt/lakshmi
git clone "$GITHUB_REPO_URL" /opt/lakshmi
cd /opt/lakshmi/deploy
ls
# EXPECT: DEPLOY.md  docker-compose.yml  nginx-lakshmi.conf  .env.production.example  VPS_AGENT.md  NETLIFY_AGENT.md
```

If the repo has been updated on GitHub, use `git pull` instead of `git clone`.

---

## 4. Write `.env.production`

Create `/opt/lakshmi/deploy/.env.production` with **exactly** these keys. The agent should heredoc-write the file rather than editing interactively:

```bash
cat > /opt/lakshmi/deploy/.env.production <<EOF
DB_NAME=lakshmi
JWT_SECRET=${JWT_SECRET}
ADMIN_EMAIL=lpathreya@gmail.com
ADMIN_PASSWORD=${ADMIN_PASSWORD}
ADMIN_NAME=Lakshmi
CORS_ORIGINS=${NETLIFY_URL:-http://localhost:3000}
APP_URL=${NETLIFY_URL:-http://localhost:3000}
APP_NAME=lakshmi
RESEND_API_KEY=${RESEND_API_KEY}
RESEND_FROM=onboarding@resend.dev
EMAIL_FROM_NAME=Lakshmi Studio Ledger
EOF
chmod 600 /opt/lakshmi/deploy/.env.production
```

Verify:

```bash
grep -c '^JWT_SECRET=' /opt/lakshmi/deploy/.env.production   # EXPECT: 1
stat -c '%a' /opt/lakshmi/deploy/.env.production             # EXPECT: 600
```

---

## 5. Prepare the uploads directory

```bash
mkdir -p /opt/lakshmi/deploy/data/uploads
# Docker's default UID inside python:3.11-slim is root (0); the bind mount is
# writable because /opt/lakshmi/deploy/data/uploads is owned by root already.
# If the container ever runs as a non-root user, adjust ownership here.
```

---

## 6. Bring the stack up

```bash
cd /opt/lakshmi/deploy
docker compose --env-file .env.production up -d --build
docker compose ps
# EXPECT: two services listed with STATUS "Up" and "healthy" (mongo needs ~15s to become healthy)

# Poll the health endpoint
for i in 1 2 3 4 5 6 7 8 9 10; do
  if curl -fsS http://127.0.0.1:8001/api/ >/dev/null; then
    echo "backend up"; break
  fi
  sleep 3
done
curl -fsS http://127.0.0.1:8001/api/
# EXPECT: {"message":"Dance Billing API"}
```

If the backend does not come up:

```bash
docker compose logs --tail=100 backend
```

Common causes: missing `.env.production` key → the compose file uses `${VAR:?...}` for required vars, so the error will name the missing key.

---

## 7. Install the nginx site + provision TLS

```bash
sudo cp /opt/lakshmi/deploy/nginx-lakshmi.conf \
        /etc/nginx/sites-available/sms.saisanathana.com

# Idempotent symlink
sudo ln -sf /etc/nginx/sites-available/sms.saisanathana.com \
            /etc/nginx/sites-enabled/sms.saisanathana.com

sudo nginx -t
# EXPECT: "syntax is ok" and "test is successful"
sudo systemctl reload nginx

# Provision the cert (non-interactive)
sudo certbot --nginx \
  --non-interactive --agree-tos --redirect \
  --email lpathreya@gmail.com \
  -d sms.saisanathana.com

# Verify HTTPS
curl -sSI https://sms.saisanathana.com/api/ | head -n1
# EXPECT: HTTP/2 200
```

If certbot fails with "unauthorized" or "connection refused":
- The A record hasn't propagated → wait a minute and retry.
- Port 80 is blocked by a firewall → `sudo ufw status` and open 80/443.

If certbot succeeds but curl to HTTPS fails:
```bash
curl -sSI https://sms.saisanathana.com/api/ -v 2>&1 | tail -20
```
Look for TLS handshake errors or the wrong `Host` header.

---

## 8. Report back to the user

Print (and preserve in the session log) these facts:

```
Backend base URL   : https://sms.saisanathana.com
Health check       : https://sms.saisanathana.com/api/
Admin login email  : lpathreya@gmail.com
Storage backend    : local (files land in /opt/lakshmi/deploy/data/uploads)
Email transport    : ${RESEND_API_KEY:+resend-direct}${RESEND_API_KEY:-DISABLED — set RESEND_API_KEY and re-run step 9}
```

**Now hand control back to the human OR proceed to `NETLIFY_AGENT.md`.**

---

## 9. Post-Netlify CORS refresh (do this AFTER Netlify is up)

Once Netlify is deployed and its URL is known:

```bash
NETLIFY_URL="https://<slug>.netlify.app"      # ask the user for the exact URL

sed -i \
  -e "s|^CORS_ORIGINS=.*|CORS_ORIGINS=${NETLIFY_URL}|" \
  -e "s|^APP_URL=.*|APP_URL=${NETLIFY_URL}|" \
  /opt/lakshmi/deploy/.env.production

cd /opt/lakshmi/deploy
docker compose --env-file .env.production up -d backend
# EXPECT: "Recreated" or "Started" — not "Up-to-date"

# Verify from a real browser origin
curl -sSI -H "Origin: ${NETLIFY_URL}" https://sms.saisanathana.com/api/ | grep -i access-control-allow-origin
# EXPECT: access-control-allow-origin: ${NETLIFY_URL}
```

---

## 10. Verification — end-to-end login

```bash
# 10a. Login via the browser at ${NETLIFY_URL}/login using
#      lpathreya@gmail.com / ${ADMIN_PASSWORD}.
# 10b. If login succeeds and the dashboard renders → DONE.
# 10c. If login fails, capture the browser Network tab for the failing request
#      and check `docker compose logs backend --tail=50`.
```

---

## 11. Rollback / troubleshooting matrix

| Symptom | Command to diagnose | Fix |
| --- | --- | --- |
| `docker compose up` errors on required env | Re-read `docker-compose.yml`; the offending var uses `${X:?...}` | Fill the value in `.env.production` |
| `nginx -t` fails after copying the conf | `sudo nginx -t` prints the exact line | Compare against `deploy/nginx-lakshmi.conf` in the repo |
| certbot: "no server-name matched" | `sudo nginx -T \| grep sms.saisanathana` | Confirm the symlink in `sites-enabled` was created |
| 502 Bad Gateway from nginx | `curl -fsS http://127.0.0.1:8001/api/` from the VPS | If that also fails, `docker compose logs backend --tail=80` |
| CORS error in browser | `curl -sSI -H "Origin: ${NETLIFY_URL}" https://sms.saisanathana.com/api/` | Fix `CORS_ORIGINS` and rerun Step 9 |
| Password reset email never arrives | `docker compose logs backend \| grep -i reset` | If `RESEND_API_KEY` is empty the link is logged only. Add the key and `docker compose up -d backend` |
| Photo upload returns 500 | `docker compose logs backend --tail=30` | Almost always a permissions problem on `data/uploads/`. `sudo chown -R $(id -u):$(id -g) /opt/lakshmi/deploy/data/uploads` |

---

## 12. Ongoing operations (reference)

**Update after `git pull`:**
```bash
cd /opt/lakshmi && git pull
cd deploy
docker compose --env-file .env.production build backend
docker compose --env-file .env.production up -d backend
docker compose logs -f --tail=50 backend
```

**Backup (nightly cron):**
```bash
# Add via `crontab -e`
5 3 * * *  cd /opt/lakshmi/deploy && \
           docker compose exec -T mongo mongodump --archive --gzip \
             > /opt/lakshmi/backups/$(date +\%Y\%m\%d).mongo.gz && \
           tar czf /opt/lakshmi/backups/$(date +\%Y\%m\%d).uploads.tgz \
             -C /opt/lakshmi/deploy/data uploads && \
           find /opt/lakshmi/backups -mtime +14 -delete
```

**Certificate renewal:** handled automatically by the `certbot.timer` systemd unit installed with the package. Verify:
```bash
sudo systemctl status certbot.timer
sudo certbot renew --dry-run
```
