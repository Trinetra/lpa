# Netlify Deployment — Agent Runbook

**Audience:** an autonomous coding agent (Claude Code / Cursor / similar) executing on the user's laptop or CI, with shell access and `npm`.
**Goal:** deploy the Lakshmi frontend from GitHub to Netlify, wire it to the VPS backend at `https://sms.saisanathana.com`.
**Total time:** ~5 minutes.

---

## 0. Guardrails for the agent

- Netlify has two supported control paths: the **CLI** (which this doc uses) and the **web UI**. The CLI path is fully scriptable — prefer it.
- **Do not** delete other Netlify sites in the user's account. Every command below is site-scoped once linked.
- **Do not** hard-code the backend URL in the React source. Only set it as a Netlify environment variable.
- If a step fails, stop and report the exact command + `stderr`. Do not retry more than twice.

---

## 1. Prerequisites the agent must confirm

```bash
node -v          # EXPECT: v18 or v20
npm -v           # EXPECT: any modern version
git -v           # EXPECT: any modern version

# The repo must already be pushed to GitHub. Confirm remote reachable:
git ls-remote "$GITHUB_REPO_URL" HEAD    # EXPECT: a single SHA line
```

If Node is missing, install via `nvm` (recommended) or the distro package.

---

## 2. Secrets the agent must collect from the user

| Variable | How the user gets it | Notes |
| --- | --- | --- |
| `NETLIFY_AUTH_TOKEN` | https://app.netlify.com/user/applications#personal-access-tokens → **New access token** → copy the value once | Store in env for this session only |
| `GITHUB_REPO_URL` | `https://github.com/<owner>/<repo>.git` | Same repo the VPS step uses |
| `BACKEND_URL` | The VPS URL you deployed in `VPS_AGENT.md` | Must be **https**, no trailing slash. Example: `https://sms.saisanathana.com` |
| `SITE_NAME` (optional) | Any lowercase-slug you want, e.g. `lakshmi-ledger` | Netlify will pick a random one if omitted |

Export before proceeding:

```bash
export NETLIFY_AUTH_TOKEN="nfp_..."
export BACKEND_URL="https://sms.saisanathana.com"
export SITE_NAME="${SITE_NAME:-}"    # empty = Netlify picks one
```

**Note about GitHub integration through CLI:** the Netlify CLI supports two site-creation paths:
- **A. CLI-managed builds** — `netlify init` uploads local builds directly (no GitHub webhook). Simplest for an agent.
- **B. GitHub-linked continuous deploys** — must be authorized once through the web UI. Recommended for a real production site.

This runbook uses **Path A** for the first-time deploy so the agent can complete end-to-end without a browser popup, then documents how the user upgrades to Path B via the web UI.

---

## 3. Install the Netlify CLI (globally, one time)

```bash
npm install -g netlify-cli@latest
netlify --version    # EXPECT: any 17.x or newer
```

If `EACCES` errors appear on Linux/macOS without `sudo`, fix `npm` prefix first (`npm config set prefix ~/.npm-global`) rather than using `sudo npm install -g`.

---

## 4. Build the frontend locally

```bash
# Working directory is the repo root
cd <repo-root>
[ -f netlify.toml ] || { echo "FAIL: netlify.toml missing"; exit 1; }

cd frontend
# CI=false suppresses treating CRA warnings as errors.
CI=false REACT_APP_BACKEND_URL="$BACKEND_URL" yarn install --frozen-lockfile
CI=false REACT_APP_BACKEND_URL="$BACKEND_URL" yarn build

# Verify the build artefact exists
ls build/index.html          # EXPECT: file exists
grep -c "$BACKEND_URL" build/static/js/*.js   # EXPECT: at least 1 hit — proves the URL is baked in
```

---

## 5. Create + link a Netlify site (Path A, CLI-driven)

```bash
cd <repo-root>/frontend

# 5a. Create a new site owned by the authenticated user
if [ -n "$SITE_NAME" ]; then
  netlify sites:create --name "$SITE_NAME" --json > /tmp/netlify-site.json
else
  netlify sites:create --json > /tmp/netlify-site.json
fi

SITE_ID=$(python3 -c "import json,sys;print(json.load(open('/tmp/netlify-site.json'))['id'])")
NETLIFY_URL=$(python3 -c "import json,sys;print(json.load(open('/tmp/netlify-site.json'))['ssl_url'])")
echo "Site ID: $SITE_ID"
echo "URL    : $NETLIFY_URL"

# 5b. Link the current directory to the new site
netlify link --id "$SITE_ID"
# EXPECT: "Directory Linked" message + writes .netlify/state.json

# 5c. Set the backend URL as a persistent env var (used for future rebuilds if
# the user later switches to Path B / GitHub CI)
netlify env:set REACT_APP_BACKEND_URL "$BACKEND_URL"
netlify env:set CI false
```

---

## 6. Deploy the pre-built assets

```bash
cd <repo-root>/frontend
netlify deploy --dir=build --prod --site="$SITE_ID"
# EXPECT: "Website Draft URL" AND "Website URL" printed. The Website URL is the production URL.

# Sanity-check the deploy
curl -sSI "$NETLIFY_URL/" | head -n1                # EXPECT: HTTP/2 200
curl -sS   "$NETLIFY_URL/api-status" -o /dev/null   # should NOT hit Netlify — just a smoke that 404 -> index.html works via SPA rule
curl -sS   "$NETLIFY_URL/some-unknown-route" | grep -q "<div id=\"root\"" && echo "SPA redirect OK"
```

---

## 7. Post-deploy — update the VPS backend CORS/APP_URL

The VPS backend needs to know the exact Netlify origin to allow browser calls and to build password-reset links.

**Hand `$NETLIFY_URL` back to the agent running `VPS_AGENT.md`** (or the same agent, switching hosts) and have it run **Step 9 of `VPS_AGENT.md`**. Without that step, the app will show `CORS error` on every request from Netlify.

Verify from Netlify's browser perspective:

```bash
curl -sSI -H "Origin: $NETLIFY_URL" "$BACKEND_URL/api/" | grep -i access-control-allow-origin
# EXPECT: access-control-allow-origin: $NETLIFY_URL
```

---

## 8. Smoke test in the browser

Open `$NETLIFY_URL/login` in a browser and log in with `lpathreya@gmail.com` / `$ADMIN_PASSWORD`.

Expected end state:
- ✅ Dashboard renders with your studio's totals.
- ✅ Navigating to any route (e.g. `$NETLIFY_URL/students`) works even after a hard refresh (proves SPA redirect).
- ✅ Uploading a photo persists across a reload (proves the VPS `data/uploads/` bind mount).
- ✅ Password reset email is received (only if `RESEND_API_KEY` was set on the VPS — otherwise the link is only in backend logs).

---

## 9. Upgrade to GitHub-continuous-deploy (recommended, human-in-loop)

Once Path A is working, switch to Path B for auto-deploys on every git push:

1. In the Netlify UI: open the site → **Site settings → Build & deploy → Continuous deployment → Link repository**.
2. Authorize GitHub, pick the repo, branch = `main`.
3. Netlify auto-detects `netlify.toml` at the repo root — leave build settings as-is.
4. Under **Environment variables** confirm `REACT_APP_BACKEND_URL` is set to your VPS URL. (`netlify env:set` in Step 5c already stored it.)
5. Trigger a first CI build to verify.

From this point, every `git push` to `main` triggers a Netlify build automatically. Step 6 (`netlify deploy --prod`) becomes redundant.

---

## 10. Rollback / troubleshooting matrix

| Symptom | Diagnose | Fix |
| --- | --- | --- |
| `netlify sites:create` returns 401 | `NETLIFY_AUTH_TOKEN` unset or wrong | Regenerate at https://app.netlify.com/user/applications |
| Build fails with `treating warnings as errors` | Missing `CI=false` | The build command in `netlify.toml` already sets it — check env override |
| Deploy succeeds but the site loads a Netlify 404 on refresh at `/students` | `netlify.toml` missing or misplaced | Confirm `netlify.toml` is at repo root, not inside `frontend/` |
| Browser: CORS error | VPS backend `CORS_ORIGINS` doesn't include Netlify URL | Run Step 9 of `VPS_AGENT.md` |
| Browser: mixed-content warning | Frontend is HTTPS but `REACT_APP_BACKEND_URL` is HTTP | Set backend URL to `https://…` and rebuild |
| Login works but every subsequent request 401s | Cookies blocked (3rd-party); `Bearer` fallback also failed | Confirm `sessionStorage` has `kalpana_access_token` after login — if not, the login response didn't include a token; check backend `/api/auth/login` response body |

---

## 11. What to hand back to the user at the end

Print exactly these facts (redacting the auth token):

```
Netlify site ID       : $SITE_ID
Netlify production URL: $NETLIFY_URL
Backend URL bound to  : $BACKEND_URL
Admin login page      : $NETLIFY_URL/login
Continuous deploy?    : No — currently manual `netlify deploy --prod`. Follow section 9 to enable.
```
