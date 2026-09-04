# Server Web Admin Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run DZMMBot continuously on Ubuntu with a login-protected web admin and an authenticated in-admin Chromium control surface.

**Architecture:** Split the existing FastAPI admin, bot scheduler, and virtual browser into systemd-managed processes behind Nginx. Keep application ports and noVNC on loopback, store mutable data outside releases, and deploy releases using an atomic `current` link.

**Tech Stack:** Ubuntu, Python 3.12, FastAPI, SQLite WAL, systemd, Nginx, Chromium/Playwright, Xvfb, x11vnc, noVNC.

**Spec:** `docs/superpowers/specs/2026-09-04-server-admin-referral-design.md`

## Global Constraints

- Public entry is the server IP; no domain and no client-IP allowlist in phase one.
- Raw VNC/noVNC, bot API, SQLite, and Chromium debugging ports are never public.
- Web-admin password must differ from SSH credentials and is never committed or logged.
- Current data is authoritative; local logs and browser history are excluded from migration.

---

### Task 1: Add server-mode authentication

**Files:**
- Create: `source/app/admin_auth.py`
- Modify: `source/main.py`
- Modify: `source/requirements.txt`
- Modify: `source/web/index.html`
- Modify: `source/web/app.js`
- Test: `source/tests/test_admin_auth.py`

**Interfaces:**
- Produces: `AdminAuth.login()`, `AdminAuth.require_session()`, `AdminAuth.logout()`, CSRF validation, `/api/auth/session`, `/api/auth/login`, and `/api/auth/logout`.

- [ ] Add failing TestClient tests for unauthenticated API rejection, correct and incorrect login, rate limiting, HttpOnly/SameSite cookie, CSRF on mutations, and logout invalidation.
- [ ] Run `python -m pytest -q source/tests/test_admin_auth.py` and confirm it fails because authentication is absent.
- [ ] Implement password-hash verification from environment, random server-side sessions with expiry, CSRF tokens, and a FastAPI dependency applied to `/api/*` except login/health.
- [ ] Add a minimal login view and ensure the existing application is rendered only after session verification.
- [ ] Re-run auth tests and commit with `feat: protect web admin with login sessions`.

### Task 2: Split bot lifecycle from the web process

**Files:**
- Create: `source/bot_service.py`
- Modify: `source/main.py`
- Modify: `source/app/scheduler.py`
- Test: `source/tests/test_server_lifecycle.py`

**Interfaces:**
- Produces: a bot service entry point and a loopback control/status contract used by the web admin.

- [ ] Add failing tests that web startup does not create a second scheduler, status reports login/Socket.IO/last-message fields, and protected restart/reconnect requests are serialized.
- [ ] Run the lifecycle tests and verify failure from the current in-process lifespan.
- [ ] Move scheduler ownership into `bot_service.py`; expose a local Unix-socket or loopback authenticated control endpoint while web remains presentation/API only.
- [ ] Re-run lifecycle and existing scheduler tests; commit with `refactor: separate bot and web service lifecycles`.

### Task 3: Add protected browser-control proxy and status UI

**Files:**
- Modify: `source/main.py`
- Modify: `source/web/index.html`
- Modify: `source/web/app.js`
- Modify: `source/web/style.css`
- Test: `source/tests/test_admin_auth.py`
- Test: `source/tests/test_browser_socket_auth.py`

**Interfaces:**
- Consumes: loopback noVNC at `127.0.0.1:6080` and bot status contract.
- Produces: authenticated `/browser/` proxy authorization and admin status/browser pages.

- [ ] Add failing tests that unauthenticated browser proxy requests are denied and sensitive token/key values never appear in status responses.
- [ ] Implement a short-lived signed browser ticket issued only to logged-in sessions; Nginx `auth_request` validates it before proxying noVNC WebSockets.
- [ ] Render service, login, Socket.IO, rooms, last-send/receive, error, and reconnect information plus the embedded browser surface.
- [ ] Run focused UI/auth tests and commit with `feat: add authenticated server browser control`.

### Task 4: Create reproducible Ubuntu deployment assets

**Files:**
- Create: `deploy/requirements-server.txt`
- Create: `deploy/env/dzmmbot.example.env`
- Create: `deploy/scripts/provision.sh`
- Create: `deploy/scripts/deploy.sh`
- Create: `deploy/scripts/migrate-data.sh`
- Create: `deploy/systemd/dzmmbot.service`
- Create: `deploy/systemd/dzmmbot-web.service`
- Create: `deploy/systemd/dzmmbot-browser.service`
- Create: `deploy/nginx/dzmmbot.conf`
- Test: `source/tests/test_server_packaging.py`

**Interfaces:**
- Produces: idempotent provisioning, release deployment, data migration, systemd units, and loopback-only Nginx topology.

- [ ] Add failing file-contract tests for service users, absolute directories, loopback bindings, environment-file permissions, health check, release symlink rollback, and absence of embedded credentials.
- [ ] Run `python -m pytest -q source/tests/test_server_packaging.py` and confirm missing-file failures.
- [ ] Implement scripts with `--apply` guard, explicit `/opt/dzmmbot`, `/var/lib/dzmmbot`, `/var/log/dzmmbot`, and `/etc/dzmmbot` targets; install Python, Nginx, Xvfb, Fluxbox, x11vnc, noVNC, and Playwright Chromium.
- [ ] Add systemd hardening and Nginx routes; validate with `bash -n deploy/scripts/*.sh` and the packaging test.
- [ ] Commit with `feat: add reproducible Ubuntu deployment`.

### Task 5: Deploy, migrate, and verify the new server

**Files:**
- Use: `source/scripts/export_current_data.py`
- Use: `deploy/scripts/provision.sh`
- Use: `deploy/scripts/deploy.sh`
- Use: `deploy/scripts/migrate-data.sh`

**Interfaces:**
- Target: Ubuntu host `124.223.175.168` using the user-provided SSH account; credentials remain interactive/in-memory.

- [ ] Run the complete local test suite and record the passing count.
- [ ] Export the authoritative current data with the allowlisted exporter and separately stage the authorized secret file; verify SQLite integrity and manifest hashes.
- [ ] Connect over SSH, inspect OS/disk/memory/firewall without changing state, then run provisioning only after checks pass.
- [ ] Upload a revisioned release and data archive over SSH, migrate into the persistent directory, and set a new web-admin password distinct from SSH.
- [ ] Stop the local robot immediately before enabling the server robot, then start all systemd services.
- [ ] Verify systemd, Nginx authentication, browser control, aikda login persistence, Socket.IO incoming messages, one outgoing test, image paths, and referral 1/3 to settlement behavior.
- [ ] If any verification fails, stop the server bot and restore the previous release/data snapshot before retrying.
