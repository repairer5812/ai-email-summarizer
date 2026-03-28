# ui/routes.py Refactor Plan

## Goal

Reduce the size and coupling of `src/webmail_summary/ui/routes.py` without changing user-visible behavior.

## Why This File Is The First Target

`src/webmail_summary/ui/routes.py` currently mixes multiple concerns:

- HTML route handlers
- settings reads and writes
- update checking and installer handoff
- cloud API key validation
- IMAP setup test flow
- lifecycle and shutdown endpoints

That makes future bug fixes harder because unrelated behaviors live in the same module.

## Refactor Principle

Use behavior-preserving extraction first.

That means:

- move cohesive helper clusters as-is,
- keep existing endpoint paths unchanged,
- keep the FastAPI response shapes unchanged,
- avoid rewriting logic during the first split.

## Phase Order

### Phase 1: Extract update domain

Target module: `src/webmail_summary/ui/updates.py`

Move:

- app version helpers
- GitHub release check logic
- installer asset selection
- updater download and verification helpers
- update apply thread state helpers
- `/updates/*` route handlers

Keep in `routes.py`:

- `home()` calling imported update helpers
- template globals setup using imported app-version helper

Why first:

- high cohesion
- low coupling to message views/setup forms
- large size reduction with minimal template impact

### Phase 2: Extract setup service helpers

Target module: `src/webmail_summary/ui/setup_service.py`

Move:

- IMAP test logic
- cloud API key test logic
- directory picker helper
- reusable setup defaults/context builders

Keep route signatures stable in `routes.py` or move route handlers later after helper extraction is stable.

### Phase 3: Extract settings gateway

Target module: reuse `src/webmail_summary/index/settings.py`

Actions:

- remove `_get_setting` and `_set_setting` duplicates from `ui/routes.py`
- remove raw one-off settings SQL where possible
- centralize normalization and persistence rules

### Phase 4: Split view routes

Candidate route modules:

- `src/webmail_summary/ui/routes_home.py`
- `src/webmail_summary/ui/routes_messages.py`
- `src/webmail_summary/ui/routes_setup.py`
- `src/webmail_summary/ui/routes_lifecycle.py`

This phase should happen only after helper extraction reduces shared utility churn.

## Safe Extraction Rules

1. Move code verbatim first.
2. Import moved helpers back into `routes.py`.
3. Keep endpoint paths and template context keys unchanged.
4. Verify after each phase with `compileall` and `pytest`.
5. Add regression tests when extracting behavior-heavy paths.

## First Concrete Extraction

Recommended immediate extraction:

- create `src/webmail_summary/ui/updates.py`
- move update helpers and `/updates/*` handlers into it
- include its router from `src/webmail_summary/ui/routes.py`
- import `_get_app_version`, `_build_update_state`, `_check_github_release`, `_DEFAULT_UPDATE_REPO`, `_schedule_app_shutdown`

## Success Criteria

- `src/webmail_summary/ui/routes.py` loses the update subsystem block
- app behavior remains unchanged
- all update endpoints still work under the same URLs
- home/setup pages still show the same update/version state
- tests still pass
