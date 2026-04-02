# macOS Smoke Test Checklist

This checklist is for the first real macOS validation pass.

Goal:

- verify that the current cross-platform preparation work behaves correctly on macOS,
- catch platform-specific breakage before native packaging work begins,
- keep test evidence reproducible for a maintainer who did not implement the changes.

## Scope

This checklist targets source-run and browser-mode validation first.

It does **not** assume:

- signed `.app` packaging,
- notarization,
- native updater parity,
- tray/background parity with Windows.

## Pre-Check

Prepare a clean macOS machine or VM with:

- macOS version recorded
- Python 3.10+ available
- IMAP test account available
- Obsidian installed or an empty vault directory prepared
- at least one cloud API key if cloud summary path will be tested

Record these before starting:

- machine model / architecture (`arm64` or `x86_64`)
- macOS version
- Python version
- whether the test is source-run only or wrapped app

## Test 1: App Data Path

### Step

Run the app once in source mode.

Expected path root:

- `~/Library/Application Support/WebmailSummary`

### Verify

Confirm the directory is created and contains runtime files such as:

- `db.sqlite3`
- `runtime/`
- `logs/`

### Fail If

- data appears under Windows-like path assumptions
- the app falls back to an unexpected dot-directory without reason

## Test 2: Browser-Mode Launch

### Step

Run:

```bash
python -m webmail_summary serve
```

or:

```bash
python -m webmail_summary ui
```

on macOS.

### Verify

- server starts
- browser opens or reachable localhost URL is printed/available
- dashboard loads without template/asset errors

### Fail If

- process exits immediately
- localhost never responds
- static assets fail to load

## Test 3: Setup Flow

### Step

Open `/setup` and save a minimal configuration.

### Verify

- IMAP fields save correctly
- cloud/local AI settings save correctly
- `obsidian_root` default feels reasonable on macOS
- no Windows-specific strings or path hints appear unexpectedly

### Fail If

- save redirects fail
- keyring lookup/save raises visible errors
- setup silently claims success but values do not persist

## Test 4: Keyring / Keychain Behavior

### Step

Store a cloud API key and, if possible, IMAP password through the app.

### Verify

- macOS Keychain prompt behavior is understandable
- after app restart, stored credentials are still retrievable
- switching Python executable or environment does not unexpectedly lose access

### Fail If

- repeated unexplained prompts appear every run
- credentials save but cannot be read back
- backend exceptions are swallowed and the UI simply behaves as if no key exists

## Test 5: Sync Flow

### Step

Run a small sync against a safe mailbox/folder.

### Verify

- mail is fetched
- archive files are created
- SQLite rows are created/updated
- per-message summaries are generated
- changed dates produce refreshed `daily_overview`

### Fail If

- sync worker crashes
- mail is archived but summary/export flow stops
- `daily_overview` is not refreshed for changed dates

## Test 6: Obsidian Export Path

### Step

Point the app to a writable vault-like folder and sync at least one message.

### Verify

- message note created
- daily note created
- topic note created when applicable
- exported file names/paths are valid on macOS

### Fail If

- path separators or path normalization break writes
- files are created in an unexpected location

## Test 7: Local llama.cpp Engine Path

### Step

Attempt local engine install or validate an already-downloaded engine.

### Verify

- correct macOS asset is selected for machine architecture
- extracted binaries are found by provider logic
- `llama-server` or `llama-cli` executable is runnable

### Fail If

- no suitable asset is found despite available upstream release
- binary is found but not executable
- provider still assumes `.exe`

## Test 8: Cloud Summary Path

### Step

Switch to cloud backend and run at least one summary.

### Verify

- provider key is read correctly
- summary succeeds
- optional cloud multimodal setting behaves as expected

### Fail If

- API key retrieval fails only on macOS
- multimodal toggle breaks text-only summaries

## Test 9: Single-Instance Behavior

### Step

Start the app twice.

### Verify

- only one active UI/server instance remains authoritative
- second launch does not corrupt runtime state

### Fail If

- both instances race on the same DB/runtime files
- stale lock prevents legitimate restart

## Test 10: Shutdown / Restart Sanity

### Step

Close the UI/browser and relaunch.

### Verify

- app exits or stays alive according to intended browser-mode behavior
- relaunch does not require manual cleanup

### Fail If

- orphaned server processes remain
- port reuse fails frequently after close/reopen

## Evidence To Capture

For every failed step, save:

- screenshot
- exact command run
- console output
- `server.log`
- relevant runtime file paths

## Exit Criteria For “Stage 2 Passed”

All of the following should be true:

- browser-mode launch works on macOS
- setup persists correctly
- keyring/keychain works acceptably
- sync + summary + export complete successfully
- local or cloud summary path works at least once
- `daily_overview` refreshes correctly
- no hard Windows path assumptions remain in the exercised path

If any of these fail, fix those before attempting native packaging or updater work.
