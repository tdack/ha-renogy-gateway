---
name: renogy-run-and-operate
description: >-
  Operational runbook for the ha-renogy-gateway HA custom integration. Load
  when executing an approved release step by step (edit CHANGELOG.md, bump
  manifest.json, commit "Bump to X.Y.Z", create the annotated vX.Y.Z tag,
  push order, HACS update visibility), publishing via HACS,
  understanding CI behaviour on tags, operating a live install (reload,
  reauth, entity availability, device grouping), pulling diagnostics for an
  issue report, enabling debug logging, or checking branding/icon delivery.
---

# Renogy Gateway: run and operate

Operational runbook for releasing and operating the `renogy_gateway` HA
custom integration. All paths are relative to the ha-renogy-gateway repo
root unless stated otherwise. Version facts are as of v0.5.1 (2026-07-12).

**When NOT to use this skill:**

- Dev environment setup, test running, dependency install → `renogy-build-and-env`.
- Change gating policy, evidence bars, and release *checklists* (what must
  be true before a release is allowed) → `renogy-change-control`. This
  skill is the mechanical runbook: the exact commands and sequence once a
  release has been approved. Do not restate change-control policy here.

## Release runbook

Governing rule (`CLAUDE.md`): **never tag a release without a matching
CHANGELOG.md entry.** Update `CHANGELOG.md`, commit it with (or just
before) the version bump, then tag.

Observed pattern from real history (verified against tags v0.5.0 and
v0.5.1, 2026-07-12): a single commit titled `Bump to X.Y.Z` touches
exactly `CHANGELOG.md` + `custom_components/renogy_gateway/manifest.json`,
followed by an **annotated tag** `vX.Y.Z` whose message is a bulleted
summary of the release.

### Steps

1. Confirm a clean tree and identify the previous tag:

   ```sh
   git status
   git describe --tags --abbrev=0
   git log --oneline "$(git describe --tags --abbrev=0)"..HEAD
   ```

2. Add a `CHANGELOG.md` entry for the new version at the top (below the
   file header), matching the existing style — `## [X.Y.Z] - YYYY-MM-DD`
   heading, then plain `-` bullets, past-tense-free imperative summaries,
   backticked identifiers, wrapped at ~76 columns:

   ```markdown
   ## [0.6.0] - 2026-07-12

   - Summarise the notable change, naming the affected `field` or module
     and, where useful, the reason it matters to a user.
   ```

3. Bump `"version"` in `custom_components/renogy_gateway/manifest.json`
   to `X.Y.Z` (no `v` prefix in the manifest).

4. Commit both files together as the bump commit:

   ```sh
   git add CHANGELOG.md custom_components/renogy_gateway/manifest.json
   git commit -m "Bump to 0.6.0"
   ```

5. Create an **annotated** tag with a bulleted message summarising the
   release (mirror the changelog bullets, condensed):

   ```sh
   git tag -a v0.6.0 -m "v0.6.0

   - First notable change
   - Second notable change"
   ```

6. **Stop here.** An AI session prepares the commit and tag but does not
   push unless the human explicitly says to. When told to publish:

   ```sh
   git push origin main
   git push origin v0.6.0
   ```

Tag format is `vX.Y.Z`; manifest version is `X.Y.Z`; changelog heading is
`[X.Y.Z]`. Keep all three in agreement.

## CI behaviour on release

Two workflows (contents verified 2026-07-12):

- `.github/workflows/test.yml` ("Test") — triggers on **every push
  (including tag pushes)** and on pull requests. One job (`pytest`):
  checkout, Python 3.13, `pip install -r requirements_test.txt`, `pytest`.
- `.github/workflows/validate.yml` ("Validate") — triggers on push **to
  the `main` branch only** (deliberately not tags), pull requests, a
  weekly cron (`0 0 * * 0`, Sundays 00:00 UTC), and `workflow_dispatch`.
  Two jobs: `hassfest` (`home-assistant/actions/hassfest@master`) and
  `hacs` (`hacs/action@main` with `category: integration`).

Validate deliberately skips tag pushes (commit `8db60f6`): `hacs/action`
resolves the manifest via the GitHub API using the pushed ref, and on a
freshly pushed tag the API has not always replicated the ref yet, so the
manifest fetch returned `None` and validation failed even though the
identical commit had just passed on the `main` push. **Do not "fix" this
by re-adding tags to Validate's triggers.** So after a release push,
expect: Test runs twice (main push + tag push), Validate runs once (main
push only). A Validate run absent on the tag is correct, not a failure.

To validate a tagged commit on demand, use `workflow_dispatch` on the
Validate workflow from the GitHub Actions UI, or rely on the weekly cron.

## HACS distribution

- Distributed as a **HACS custom repository** (not in the default store).
  Install steps are in `README.md`: HACS → Integrations → ⋮ → Custom
  repositories → add `https://github.com/tdack/ha-renogy-gateway`,
  category **Integration**, install, restart HA. The README also carries a
  My Home Assistant `hacs_repository` badge that deep-links this flow.
- `hacs.json` (entire contents): `{"name": "Renogy Gateway",
  "render_readme": true}` — HACS shows the rendered `README.md` as the
  integration's info page.
- **Git tags are HACS versions.** Pushing `vX.Y.Z` is what makes the
  release visible as an update in HACS; HACS reads the version from the
  tagged `manifest.json`. No GitHub Release object is required, but the
  tag push is.

## Branding delivery

Two mechanisms, both containing the same Renogy icon/logo set (sourced
from `home-assistant/brands` `custom_integrations/renogy/`, per
`README.md`):

- `custom_components/renogy_gateway/brand/` — **bundled, active.** Home
  Assistant 2026.3+ serves these locally via the Brands Proxy API with no
  extra configuration; the icon appears immediately after install.
  Contains `icon.png`, `icon@2x.png`, `logo.png`, `logo@2x.png`,
  `dark_logo.png`, `dark_logo@2x.png`.
- `brands/custom_integrations/renogy_gateway/` — **staging copy,
  open/candidate.** Same six files in the legacy layout, prepared for a
  future PR to `home-assistant/brands` covering older HA versions. As of
  2026-07-12 that PR has not been submitted; do not describe it as done.

When adding/replacing brand images, keep both locations in sync.

## Operating a live install

- **Reauth:** when setup hits a `RenogyAuthError`, `coordinator.py`
  raises `ConfigEntryAuthFailed`, which makes HA show a "Reauthenticate"
  repair/notification. `config_flow.py` `async_step_reauth` →
  `async_step_reauth_confirm` asks for email + password again, performs a
  fresh login, writes the new token set into the entry, and explicitly
  drops any stored password (`new_data.pop(CONF_PASSWORD, None)`).
  Passwords are never persisted (removed in 0.4.0; entry migration v1→v2
  strips any previously stored one).
- **Reload** (Settings → Devices & services → Renogy Gateway → ⋮ →
  Reload): full teardown and re-setup — RTM WebSocket reconnect, complete
  rediscovery (`gwm.devs`/`get_product`/`get_model`), initial read of all
  readable fields, re-subscribe of all subscribable fields, and a fresh
  scene fetch. Rediscovery merges non-destructively (0.5.0): a device that
  transiently resolves to zero fields keeps its prior schema instead of
  tearing down its entities.
- **Device grouping:** one HA device per Renogy device, keyed by
  `did_str`, including the **gateway (ONE Core) itself** since 0.5.0.
  Metadata-only devices (e.g. "Vision") are registered explicitly in
  `__init__.py` even though they own no entities. Multi-namespace devices
  (e.g. an inverter with `ac_input`/`ac_output`/`charger`) must group
  under a single HA device — there is a regression test for this.
- **Availability:** since 0.4.0, an unexpected WebSocket drop flips all
  entities to `unavailable` and starts a background reconnect loop with
  exponential backoff (2 s doubling to a 30 s cap —
  `RTM_RECONNECT_DELAY_MIN`/`MAX` in `const.py`). Entities recover
  automatically when it reconnects. Entities stuck unavailable with no
  recovery suggests a pre-0.4.0 build or an auth failure (check for a
  reauth prompt).
- **Scenes:** fetched via REST at every connect/reconnect
  (`_refresh_scenes`), exposed as a run button (Manual scenes) and an
  enable switch (Auto scenes). Scene fetch failure is non-fatal — the
  rest of the integration starts without them.

## Diagnostics

Download in the HA UI: Settings → Devices & services → Renogy Gateway →
⋮ on the config entry → **Download diagnostics**.

Safe to attach to a GitHub issue from 0.4.0+: no credentials or tokens
survive redaction (email redaction was added in 0.4.0 — treat diagnostics
from older builds as containing the account email). It does expose device
serial-ish `did_str`s, SKUs, and user-assigned device names — mention that
to the user, but they are not secrets. No raw telemetry values or field
lists are included. Full payload structure and the `_REDACT` key list →
`renogy-diagnostics-and-tooling` §1.1.

## Debug logging

The manifest declares `"loggers": ["custom_components.renogy_gateway"]`,
so both routes work:

- **UI (preferred):** Settings → Devices & services → Renogy Gateway →
  **Enable debug logging**. Disabling it afterwards offers the captured
  log slice for download.
- **YAML** (`configuration.yaml`, then restart or reload logger):

  ```yaml
  logger:
    default: warning
    logs:
      custom_components.renogy_gateway: debug
  ```

A healthy startup at debug level reads: `"Discovered %d devices behind
gateway %s"` → possibly a few per-`sp` read/subscribe failures (tolerated)
→ `"Subscribed to %d fields"` → `"Discovered %d scenes"`. The full
log-line format-string table (every line, verbatim, with interpretations)
→ `renogy-diagnostics-and-tooling` §1.2.

## Data and artifact conventions

- **Tokens live in the HA config entry**, nothing else. The coordinator
  passes a `_persist_tokens` callback to the auth layer that calls
  `hass.config_entries.async_update_entry` on every rotation, and setup
  restores tokens from `entry.data`. Verified 2026-07-12: no
  `helpers.storage.Store` usage and no file writes anywhere in
  `custom_components/renogy_gateway/` — there are no local caches or
  token files to clean up.
- The account **password is never stored** (entry version 2+).
- Scenes and the device/field registry are rebuilt from the cloud on
  every connect; nothing schema-related is persisted between reloads.

## Operational safety

Any live control action — switch, light, number, select, scene button,
or scene enable switch — issues a real write to the gateway and **drives
physical circuits** on the user's power system. Never exercise a control
entity on a live install (including "just to test") without explicit
human permission for that specific action. Read-only operations
(diagnostics download, debug logs, sensor reads, reload) are safe.
Writes are schema-validated (existence, writability, type, bounds) since
0.5.0, but validation does not make an unwanted write safe.

## Provenance and maintenance

- Grounded in the ha-renogy-gateway repo at v0.5.1 (verified
  2026-07-12): `CLAUDE.md` (release rule), `git log`/`git show` around
  tags v0.5.0 and v0.5.1 (bump-commit pattern, annotated tag style),
  `.github/workflows/test.yml` and `validate.yml` (decoded in full),
  commit `8db60f6` (Validate tag-push rationale), `hacs.json`,
  `README.md` (install steps, branding section), `manifest.json`,
  `diagnostics.py` (`_REDACT` and builder), `config_flow.py` (reauth),
  `coordinator.py` (setup, reconnect, scenes, token persistence, log
  strings), `__init__.py` (device registration, migration), `const.py`
  (reconnect delays), `CHANGELOG.md` (entry style, 0.4.0/0.5.0
  behaviour).
- Re-verify when: workflow files change (especially Validate triggers),
  the brands PR to `home-assistant/brands` is actually opened/merged,
  diagnostics gains new sections or `_REDACT` keys, log strings in
  `coordinator.py` are reworded, or the release process moves to GitHub
  Releases/automation.
- Sibling repo `renogy-gateway` is the canonical protocol/curation
  source; this skill covers only the HA integration's operations.
