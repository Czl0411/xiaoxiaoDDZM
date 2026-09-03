# DZMMBot Windows Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and publish a safe Windows portable ZIP and Setup.exe while creating a separate local-only snapshot of the current Mac business data.

**Architecture:** The public repository contains source, public assets, a Windows GitHub Actions workflow, and an Inno Setup definition. PyInstaller produces one directory that feeds both public artifacts; a separate local export script creates a private data ZIP and explicitly excludes browser state, secrets, and logs.

**Tech Stack:** Python 3.12, PyInstaller, Playwright 1.49.1, GitHub Actions `windows-latest`, Inno Setup 6, PowerShell, pytest.

**Spec:** `source/docs/superpowers/specs/2026-09-03-windows-release-design.md`

## Global Constraints

- The repository is public and must never contain `bot.db`, live `config.json`, `secrets.json`, `browser_profile`, logs, or the embedded secret payload.
- Windows artifacts contain no real `data` directory and no embedded API key.
- Both artifacts contain Playwright Chromium and all public runtime assets.
- Setup.exe installs per-user without administrator rights and never installs, overwrites, or uninstalls `data`.
- The private current-data ZIP is created locally only and contains business data but excludes browser profiles, secrets, and logs.
- The existing `/Users/zhijian/Desktop/DDZM` reference project is never modified.

---

### Task 1: Public Repository Safety Boundary

**Files:**
- Create: `.gitignore`
- Create: `source/tests/test_release_packaging.py`
- Modify: `source/DZMMBot.spec`

**Interfaces:**
- Consumes: existing PyInstaller entry point `source/desktop.py`.
- Produces: a source tree that can build with an empty generated `app/_embedded_secret_payload.py` and a test that rejects sensitive tracked paths.

- [ ] **Step 1: Write failing release-safety tests**

Add tests that load `.gitignore` and `DZMMBot.spec`, assert sensitive path patterns are ignored, assert the current non-empty payload path is ignored, and assert the spec no longer raises when `DEEPSEEK_SECRET_BLOB` is empty.

- [ ] **Step 2: Verify the tests fail**

Run: `PYTHONPATH=source uv run --with-requirements source/requirements.txt --with pillow pytest -q source/tests/test_release_packaging.py`

Expected: FAIL because root `.gitignore` does not exist and the spec rejects an empty payload.

- [ ] **Step 3: Implement the safety boundary**

Create `.gitignore` with explicit rules for root build output, caches, databases, live data, browser profiles, secrets, embedded payloads, logs, local screenshots, backup Python files, and the private data ZIP. Remove only the non-empty-secret guard from `DZMMBot.spec`; retain importing `DEEPSEEK_SECRET_BLOB` so Actions can generate an empty placeholder.

- [ ] **Step 4: Verify safety tests pass**

Run the Task 1 test command and expect all tests to pass.

- [ ] **Step 5: Commit**

Commit `.gitignore`, the spec change, and the release-safety tests with message `build: establish public release safety boundary`.

### Task 2: Windows Build Workflow and Portable ZIP

**Files:**
- Create: `.github/workflows/build-windows.yml`
- Create: `source/scripts/assemble_windows_release.ps1`
- Modify: `source/tests/test_release_packaging.py`

**Interfaces:**
- Consumes: `source/DZMMBot.spec`, `source/requirements.txt`, and public asset directories.
- Produces: `release/DZMM群聊机器人/` and `release/DZMMBot-Portable-win64.zip`.

- [ ] **Step 1: Write failing workflow structure tests**

Assert the workflow uses `windows-latest`, Python 3.12, `playwright install chromium`, writes an empty payload file, invokes PyInstaller, invokes the assembly script, uploads both named artifacts, and contains no `${{ secrets.* }}` API-key injection. Assert the assembly script copies `dist/DZMM群聊机器人`, Playwright browsers, and public assets but does not copy `data`.

- [ ] **Step 2: Verify tests fail**

Run the release-packaging test file and expect missing workflow/script failures.

- [ ] **Step 3: Implement workflow and assembly script**

The workflow runs on `workflow_dispatch`, pushes to `main`, and tags matching `v*`. It installs requirements plus `pyinstaller`, installs Chromium into a workspace-local `ms-playwright`, builds the spec, assembles the release directory, compresses it, compiles the installer from Task 3, and uploads ZIP and Setup artifacts.

- [ ] **Step 4: Verify tests pass and YAML parses**

Run release-packaging tests and parse `.github/workflows/build-windows.yml` with Python `yaml.safe_load`.

- [ ] **Step 5: Commit**

Commit with message `ci: build Windows portable release`.

### Task 3: Per-User Setup.exe

**Files:**
- Create: `installer/DZMMBot.iss`
- Modify: `source/tests/test_release_packaging.py`

**Interfaces:**
- Consumes: `release/DZMM群聊机器人/` from Task 2.
- Produces: `release/DZMMBot-Setup-win64.exe`.

- [ ] **Step 1: Write failing installer policy tests**

Assert the script uses `PrivilegesRequired=lowest`, defaults to `{localappdata}\Programs\DZMMBot`, recursively installs the assembled program, creates a Start Menu shortcut, launches the EXE optionally, and contains no `[Files]` or `[UninstallDelete]` rule targeting `data`.

- [ ] **Step 2: Verify tests fail**

Run release-packaging tests and expect failure because the Inno script is missing.

- [ ] **Step 3: Implement the Inno Setup script**

Use a stable AppId, per-user install directory, `OutputBaseFilename=DZMMBot-Setup-win64`, LZMA2 compression, and source `..\release\DZMM群聊机器人\*`. Do not mention `data` in install or uninstall file rules.

- [ ] **Step 4: Verify tests pass**

Run release-packaging tests and expect all installer assertions to pass.

- [ ] **Step 5: Commit**

Commit with message `build: add per-user Windows installer`.

### Task 4: Private Current-Data Export

**Files:**
- Create: `source/scripts/export_current_data.py`
- Create: `source/tests/test_export_current_data.py`

**Interfaces:**
- Consumes: `--data-dir PATH` and `--output PATH`.
- Produces: a ZIP whose entries are rooted at `data/`, containing `bot.db`, `config.json`, `shop_images/**`, and `image_generation/**`, while excluding `browser_profile/**`, `secrets.json`, and `logs/**`.

- [ ] **Step 1: Write failing export tests**

Build a temporary data tree containing included and forbidden files, call `export_data(data_dir: Path, output: Path) -> list[str]`, and assert exact ZIP members. Add a test that fails with a clear exception when `bot.db` or `config.json` is missing.

- [ ] **Step 2: Verify tests fail**

Run: `PYTHONPATH=source uv run --with-requirements source/requirements.txt --with pillow pytest -q source/tests/test_export_current_data.py`

Expected: import failure because the exporter does not exist.

- [ ] **Step 3: Implement the exporter**

Use `zipfile.ZipFile` and explicit allowlisted roots only. Refuse an output path located inside the source data directory. Print the output path and included member count without printing file contents.

- [ ] **Step 4: Verify tests pass and create the real private ZIP**

Run the exporter against `/Users/zhijian/Desktop/DZMMBot-Portable(20260826)/data` with output `/Users/zhijian/Desktop/DZMMBot-current-data.zip`. Inspect ZIP member names and confirm no forbidden prefixes or filenames are present.

- [ ] **Step 5: Commit only script and tests**

Commit with message `feat: add safe current-data exporter`. Never add the generated ZIP.

### Task 5: User-Facing Release Instructions

**Files:**
- Create: `README.md`
- Modify: `source/发布版使用说明.txt`
- Modify: `source/tests/test_release_packaging.py`

**Interfaces:**
- Consumes: artifact names and migration contract from Tasks 2–4.
- Produces: exact instructions for portable extraction, Setup installation, importing the private data before first launch, Windows login, and entering the user's own API key.

- [ ] **Step 1: Write failing documentation contract tests**

Assert the root README names both artifacts, warns that public builds contain no data/API key, and lists the private import order. Assert the packaged user guide tells the user to stop the robot before replacing `data` and to log in again on Windows.

- [ ] **Step 2: Verify tests fail**

Run release-packaging tests and expect missing root README/instruction text failures.

- [ ] **Step 3: Write concise instructions**

Document download, installation, portable use, private data import, upgrade preservation, WebView2 troubleshooting, and API-key configuration without exposing local paths or secrets.

- [ ] **Step 4: Verify tests pass**

Run release-packaging tests and the existing runtime asset path tests.

- [ ] **Step 5: Commit**

Commit with message `docs: add Windows release and migration guide`.

### Task 6: Final Verification and Public Push

**Files:**
- Modify: none unless verification reveals a scoped defect.

**Interfaces:**
- Consumes: all prior tasks.
- Produces: a safe `main` branch on `git@github.com:Czl0411/xiaoxiaoDDZM.git` and a triggered Windows Actions run.

- [ ] **Step 1: Run focused release tests**

Run both new test files and `source/tests/test_runtime_asset_paths.py`.

- [ ] **Step 2: Run current functional regression suites**

Run: `PYTHONPATH=source uv run --with-requirements source/requirements.txt --with pillow pytest -q source/tests/test_commission_house_v2.py source/tests/test_commission_wizard.py source/tests/test_help_system_rebuild.py source/tests/test_aikda_socket.py source/tests/test_dzmm_adapter_socket.py source/tests/test_dzmm_adapter_send.py source/tests/test_image_generation.py source/tests/test_direct_chats.py`. Record failures with their exact test names and do not describe a failing suite as passing.

- [ ] **Step 3: Audit staged and tracked files**

Use `git ls-files` plus explicit forbidden-pattern checks. Verify `_embedded_secret_payload.py`, all `data` paths, database files, browser profiles, logs, caches, build output, and the private ZIP are absent.

- [ ] **Step 4: Configure remote and push**

Add `origin` as `git@github.com:Czl0411/xiaoxiaoDDZM.git`, verify the empty remote again, and push `main`. Do not force-push.

- [ ] **Step 5: Observe the Windows run**

Open the Actions run page or query its public status until it succeeds or returns actionable failure. If it fails, fix only the build issue, rerun relevant local tests, commit, and push again.

- [ ] **Step 6: Report artifacts and private data ZIP**

Provide the Actions artifact location, exact Windows import steps, the local private ZIP path, test counts, and any limitation that remains.
