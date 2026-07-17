---
name: renogy-research-frontier
description: >-
  Open problems and next-step candidates for making ha-renogy-gateway a
  best-in-class Home Assistant integration. Load when asked "what should we
  work on next", when planning a roadmap or milestone, when prioritising
  between proposed features, or when evaluating whether a proposed feature
  actually advances the project's stated goal (parity with the sibling
  dashboard, HACS default store, brands PR, long-term statistics). Each item
  carries verified current state, first concrete steps, and a falsifiable
  milestone.
---

# Renogy research frontier

Open problems standing between ha-renogy-gateway v0.5.1 and the owner's
definition of "beyond state of the art": a **best-in-class HA integration** —
feature and robustness parity with the sibling `renogy-gateway` dashboard,
HACS default-store admission, a home-assistant/brands entry, and long-term
statistics. Polish over novelty. Every item below is a **candidate** — nothing
here is committed work. Repo state was verified in source on 2026-07-12;
web-sourced facts are date-stamped inline.

## When NOT to use this skill

- **Executing curation-drift work** (UNIT_MAP / LEAF_ORDER / NS_GROUP
  reconciliation against the sibling) → use `renogy-curation-parity-campaign`.
- **Gating or landing any item below** (evidence bar, sign-off, release
  mechanics) → use `renogy-change-control`. This skill proposes; it does not
  authorise.
- Protocol details → `renogy-protocol-reference`. Build/run mechanics →
  `renogy-build-and-env`, `renogy-run-and-operate`.

## Standing obligations (apply to every item)

- **Sibling is canonical.** Parity items must match `renogy-gateway`
  (read-only) behaviour, not fork it. If the sibling is wrong, fix it there
  first (separate change, separate approval).
- **Captures are the evidence bar.** Protocol claims need a capture or a live
  observation; "the docs imply" is not evidence.
- **Never live-test writes** (including `scene.run`) without explicit owner
  permission, per repo CLAUDE.md control-safety rules.
- **Discovery over hardcoding.** No item may introduce SKU tables, channel
  allowlists, or per-device literals.

## Priority order (impact ÷ risk, for the stated goal)

1. HACS default-store admission — highest goal-relevance per unit risk; the
   repo already meets most requirements, so the residual work is process.
2. home-assistant/brands PR — near-zero risk; assets are staged and finished.
3. Long-term statistics & Energy dashboard — highest single-feature impact,
   but state-class changes write permanent statistics, so design risk is real.
4. Quality-scale ladder — medium impact (credibility + structured checklist),
   low risk; much of Bronze is already met.
5. Unit normalisation parity — small verified gap; cheap to close, guards a
   named unwritten rule (sibling canonical).
6. Options flow & tunables — useful, low risk, but no user has asked yet.
7. Reconnect/rediscovery efficiency — real inefficiency, but cache
   invalidation risk and the current behaviour is correct, just slow.
8. Scene execution live confirmation — blocked on an explicit owner-permitted
   live session; until granted, ratio is undefined, so it sits last.

---

## 1. HACS default-store admission

**Current state (verified 2026-07-12).** Distributed as a HACS *custom
repository* only. The repo already has: public GitHub home
(`tdack/ha-renogy-gateway`), `hacs.json` (`name`, `render_readme`), tagged
releases through `v0.5.1`, a substantive `README.md`, CI running both
`home-assistant/actions/hassfest` and `hacs/action` (category `integration`)
in `.github/workflows/validate.yml`, and bundled brand images at
`custom_components/renogy_gateway/brand/icon.png` (+ logo/dark variants).

**Why it falls short.** Not listed in `hacs/default`, so installation requires
the manual custom-repository dance — a discoverability and trust ceiling for a
"best-in-class" claim.

**Requirements (hacs.xyz publish docs, checked 2026-07-12).** Public GitHub
repo; `hacs.json` with at least `name`; GitHub releases; passing HACS +
hassfest actions; brand assets (HACS accepts a `brand/` dir with `icon.png`
inside the integration, falling back to a home-assistant/brands entry);
repository description and topics set on GitHub; then a PR to `hacs/default`
adding the repo alphabetically to the integration list.

**Asset.** Nearly everything is already in place — this is a checklist item,
not an engineering item.

**First three steps.**
1. Re-run the checklist against live: confirm the GitHub repo has a
   description and topics set (not verifiable from the working tree), and that
   the latest `validate.yml` run is green on `main`.
2. Cut a fresh release if `main` has moved past `v0.5.1` (changelog first, per
   `CLAUDE.md` release rules), so the submitted state matches a tag.
3. Draft the `hacs/default` PR (one-line alphabetical addition) and record the
   submission plan through `renogy-change-control` before opening it.

**You have a result when** the integration appears in the HACS default store
search in a clean HA instance with no custom repository added.

**Risks/obligations.** External review queue — timeline not under our control.
Once listed, releases become public-facing: the changelog-before-tag rule and
`renogy-validation-and-qa` gates stop being optional hygiene.

## 2. home-assistant/brands PR

**Current state (verified 2026-07-12).** A staging copy in the legacy brands
layout exists at `brands/custom_integrations/renogy_gateway/` (icon.png,
icon@2x.png, logo.png, logo@2x.png, dark_logo.png, dark_logo@2x.png) and is
documented in `README.md` ("Icon / branding") as *ready to submit, not yet
submitted*. Since the Brands Proxy API change (HA dev blog, 2026-02-24,
checked 2026-07-12), custom integrations can bundle brand images locally —
this repo already does, in `custom_components/renogy_gateway/brand/` — so the
brands PR now only benefits **older HA versions without the local-brand
fallback**.

**Why it falls short.** Users on pre-Brands-Proxy HA versions see a blank
placeholder icon; the owner's goal explicitly includes the brands entry.

**Asset.** The staging folder is finished and README-documented; the PR is
copy-paste plus upstream review.

**First three steps.**
1. Verify each staged image against current brands rules (checked
   2026-07-12): icon 256×256, @2x 512×512, PNG, directory name exactly the
   `renogy_gateway` domain, no HA-branded imagery, no symlinks.
2. Fork `home-assistant/brands`, copy
   `brands/custom_integrations/renogy_gateway/` into its
   `custom_integrations/`, and confirm the repo's CI image checks pass.
3. Record the submission plan through `renogy-change-control`, then open the
   PR; link it from a tracking issue in this repo so the pending external
   dependency is visible.

**You have a result when** `https://brands.home-assistant.io/renogy_gateway/icon.png`
serves the icon, and an HA version *without* the local-brand fallback renders
it in the integrations list.

**Risks/obligations.** Renogy trademark usage — the images are Renogy's own
brand assets; be ready to justify nominative use if upstream reviewers ask.
Keep the bundled `brand/` copy and the brands-repo copy byte-identical (a
drift here is a curation-parity problem; see
`renogy-curation-parity-campaign` for the pattern).

## 3. Long-term statistics & Energy dashboard

**Current state (verified 2026-07-12).** `sensor.py` maps `kWh`/`Wh` fields to
`SensorDeviceClass.ENERGY` with correct units via `_UNIT_MAP` (lines 46–47),
but line 125 assigns `SensorStateClass.MEASUREMENT` to **every** numeric
sensor unconditionally. There is no `TOTAL_INCREASING`, no `TOTAL`, and no
`last_reset` anywhere in the integration. Consequence: HA records short-term
statistics but the Energy dashboard cannot consume these sensors (it requires
`total`/`total_increasing` energy sensors), and long-term energy accumulation
is wrong by construction.

**Asset.** The sibling's curated history layer is a ready-made answer to
"which metrics deserve long-term treatment": `packages/core/src/history.ts`
(`buildHistoryMetrics`, allowlist-based per commit `824b83c` — explicitly
*not* namespace membership) plus its unit-scale handling. Port the *selection
logic and semantics*, not the file.

**First three steps.**
1. Read `renogy-gateway/packages/core/src/history.ts` and
   `packages/core/test/history.test.ts`; extract the allowlist criteria and
   which fields are cumulative counters vs instantaneous readings.
2. In captures/diagnostics, confirm for each candidate energy field whether
   the wire value is lifetime-cumulative, daily-resetting, or instantaneous —
   this decides `TOTAL_INCREASING` vs `TOTAL` + `last_reset` vs leaving it
   `MEASUREMENT`. Do not guess: a wrong state class writes garbage into HA's
   permanent statistics tables.
3. Prototype in `custom_components/renogy_gateway/sensor.py`: derive state
   class in `RenogySensor.__init__` from device class + the evidence from
   step 2 (schema-driven, no per-SKU tables), with tests in
   `tests/test_sensor.py` covering each class assignment.

**You have a result when** a Renogy energy sensor can be added as a source in
HA's Energy dashboard and shows correct kWh accumulation across at least one
real day, including a device reboot, with no statistics warnings in HA logs.

**Risks/obligations.** Highest-risk item on this list: long-term statistics
are effectively permanent, and changing a sensor's state class after release
creates migration pain for existing users — get the classification right
before shipping, and route the design through `renogy-change-control`.
Field-behaviour claims (cumulative vs resetting) need capture evidence.

## 4. HA quality-scale ladder

**Current state (verified 2026-07-12).** `manifest.json` has **no**
`quality_scale` key. Already in place, mapping onto Bronze-tier rules
(developers.home-assistant.io quality-scale docs, checked 2026-07-12):
UI config flow with reauth (`config_flow.py`, `async_step_reauth` at line 97),
`entry.runtime_data` (`coordinator.py`, used across platforms),
`_attr_has_entity_name = True` (`entity.py` lines 20, 92), diagnostics
platform (`diagnostics.py`), 14 test files in `tests/` including
`test_config_flow.py`, and hassfest in CI. Missing or unverified: no
`quality_scale.yaml` checklist, no options flow (see item 5), no repairs
issues, `strings.json` has `exceptions` but no `entity` translation section
(entity names are runtime-derived from discovery, so the entity-translations
rule is largely exempt-by-design — record the exemption rather than fake
compliance), and no per-rule audit has ever been done.

**Why it falls short.** For custom integrations the manifest key and
`quality_scale.yaml` have no runtime effect, but the *rules* are the closest
thing HA has to an objective "best-in-class" rubric — the stated goal.

**Asset.** The integration was written recently against modern HA patterns
(runtime_data, has_entity_name, typed config entry), so the audit starts from
a strong base rather than a rewrite.

**First three steps.**
1. Fetch the current rule list from developers.home-assistant.io and audit
   every Bronze rule against the source, recording done / todo / exempt with
   file references — put the result in
   `custom_components/renogy_gateway/quality_scale.yaml` as a living
   checklist (no runtime effect for custom integrations; that is fine).
2. Fix the cheap Bronze/Silver gaps the audit surfaces (e.g. verify
   `PARALLEL_UPDATES` on all platforms — `sensor.py` line 27 has it; check
   the others).
3. Only after the audit holds, add `"quality_scale"` to `manifest.json` at
   the tier actually met, and note it in `CHANGELOG.md`.

**You have a result when** `quality_scale.yaml` exists with every Bronze rule
marked done or exempt-with-reason, each claim backed by a file reference, and
the manifest declares that tier.

**Risks/obligations.** No overclaiming: declaring a tier the code does not
meet is worse than declaring none. Some rules assume core-integration
infrastructure; mark those exempt honestly.

## 5. Unit normalisation parity

**Current state (verified 2026-07-12).** The gap is **smaller than folklore
says** — most of this landed in 0.2.6 (`CHANGELOG.md` line 75). `sensor.py`
`_UNIT_MAP` (lines 34–51) scales `mW`/`mV`/`mA` to base units (0.001), maps
`安培`→A and `℃`→°C, and caps display precision; `number.py` reuses the same
map and scales `native_min_value`/`native_max_value` by the same factor
(lines 88–92) and divides back on write (line 112) — the direct analogue of
sibling commits `c0be656` (normalise mV/mA/mW) and `30d3d9d` (scale min/max).
Sibling commit `0d245da` (rescale history samples) has no HA counterpart
because the HA port has no history layer — that gap belongs to item 3.

**Remaining gap, precisely.** Two independent implementations of the same
rule: sibling `packages/core/src/discovery.ts` (`unitScale`) +
`params.ts` (`UNIT_MAP`) vs this repo's `sensor.py` `_UNIT_MAP`. No shared
fixture proves they produce identical values for the same field, and nothing
prevents silent divergence when either side adds a unit (e.g. a new
milli-prefixed or Chinese-labelled unit appearing in a future capture).

**Asset.** Both repos are locally checked out side by side, and captures
provide real field/unit/value triples to test against.

**First three steps.**
1. Diff the unit tables: `sensor.py` `_UNIT_MAP` vs sibling `params.ts`
   `UNIT_MAP`/`UNIT_FALLBACK` and `discovery.ts` `unitScale` handling; list
   every unit string either side handles that the other does not.
2. Build a fixture of (field, raw wire value, expected display value) triples
   from a capture, and add a test in `tests/test_sensor.py` asserting the HA
   scaled output matches the sibling's documented normalisation for each.
3. File any divergence as a curation-parity finding and hand execution to
   `renogy-curation-parity-campaign` (that skill owns the reconciliation
   workflow; do not fork behaviour here).

**You have a result when** the same field (e.g. an inverter mA current)
displays the identical scaled value and unit in the Workers dashboard and in
HA, proven by a committed fixture test rather than eyeballing.

**Risks/obligations.** Sibling is canonical — if values disagree, HA changes
(unless the sibling is provably wrong, which goes upstream first). Changing a
sensor's scale after release rewrites the meaning of recorded history for
existing users; flag any such change through `renogy-change-control`.

## 6. Options flow & tunables

**Current state (verified 2026-07-12).** `config_flow.py` implements only
`user` (credentials + gateway pick) and `reauth` steps. There is no
`OptionsFlowHandler` and no `async_get_options_flow` — confirmed absent by
search. Nothing about the integration is user-tunable post-setup.

**Why it falls short.** Silver-tier expectations and ordinary usability:
behavioural knobs currently require editing code or reloading the entry.

**What an options flow should NOT expose (honesty clause).** Anything
discovery answers: device lists, channel names, which fields are
controllable, units, dimmable-vs-switch. Exposing those as options would
violate the discovery-over-hardcoding rule and re-introduce the config drift
the architecture exists to prevent.

**Legitimate candidates** (each is a genuine runtime policy, not protocol
data): reconnect backoff bounds (`coordinator.py` `_reconnect_loop`),
diagnostic-entity verbosity (whether `is_diagnostic_field` entities are
created at all), and — if item 7 lands — a "force full rediscovery" toggle to
bypass the schema cache.

**First three steps.**
1. Confirm the candidate list against real need: check open issues and the
   owner's actual pain points before building anything (an options flow with
   no demanded options is scope creep, not polish).
2. Add `async_get_options_flow` in
   `custom_components/renogy_gateway/config_flow.py` with a single-step
   schema for the agreed options; store in `entry.options`.
3. Wire `entry.add_update_listener` in `__init__.py` to apply options without
   a full reload where possible; extend `tests/test_config_flow.py`.

**You have a result when** a user can change at least one documented runtime
option from the UI and observe the behaviour change without editing files.

**Risks/obligations.** Scope discipline — every proposed option must pass the
"is this discovery data?" test. Low protocol risk otherwise.

## 7. Reconnect/rediscovery efficiency

**Current state (verified 2026-07-12).** Every reconnect runs full discovery:
`coordinator.py` `_reconnect_loop` (lines 464–484) calls
`_connect_and_discover` (line 172), which re-runs the whole
`gwm.devs → get_product → get_model` pipeline. `api/discovery.py` has an
in-memory `_model_cache` (line 139) that deduplicates *within* one pass, but
nothing persists across reconnects or HA restarts — there is no
`homeassistant.helpers.storage.Store` usage anywhere in the integration
(confirmed by search). Sibling `docs/PROTOCOL.md` §7.6 states `get_model` is
~25–30 RPCs per pass and that the schema is **static per pid + firmware
version**, and the sibling caches resolved schemas (`product:<pid>`,
`model:<namespace>`) plus a per-rig snapshot with live revalidation
(`diffRigs`).

**Asset.** §7.6 is the design document, and the sibling's snapshot/revalidate
implementation in `packages/core/src/discovery.ts` is the reference for the
reconcile semantics (device add/remove/capability change).

**First three steps.**
1. Define the measurement first: log timestamps around
   `_connect_and_discover` and record reconnect-to-entities-available time
   plus RPC count on the current code (baseline before optimising).
2. Design the cache: a `Store`-backed snapshot keyed like the sibling
   (`product:<pid>`/firmware for schemas; rig snapshot per gateway did), with
   serve-then-revalidate semantics mirroring `diffRigs` — not a
   trust-forever cache.
3. Implement in `api/discovery.py` + `coordinator.py`, feeding the existing
   `_merge_devices` non-destructive reconcile (coordinator.py line 237, which
   already mirrors the sibling's `_runLive` behaviour); add a
   corrupt/stale-cache test in `tests/test_discovery.py`.

**You have a result when** the measured reconnect-to-available time and RPC
count drop materially (baseline vs cached, same rig, numbers recorded in the
PR), with a forced-rediscovery path proven to recover from a stale snapshot.

**Risks/obligations.** Cache-invalidation bugs here manifest as ghost or
missing entities — worse than slowness. Firmware updates must bust the cache
(pid + firmware key, per §7.6). Parity: reconcile semantics must match the
sibling, not fork.

## 8. Scene execution live confirmation

**Current state (verified 2026-07-12).** `button.py` creates a Run button per
Manual scene and `coordinator.py` `async_run_scene` (line 399) issues
`scene.run` and checks the ack code — yet `docs/PROTOCOL.md` §8.3 (line 460)
is still headed "**[model confirmed; run untested live]**". The integration
ships a physical-circuit control path that has never been exercised
end-to-end on real hardware.

**Why it falls short.** Best-in-class means no shipped control surface whose
happy path is unverified. The code is done; the *evidence* is missing.

**Asset.** The protocol doc's own label convention ([CONFIRMED LIVE …], cf.
the 06-14 cold-start entry at PROTOCOL.md line 96) defines exactly what
closing this looks like, and the ack-code handling (`code not in (0, 14)`)
gives a concrete pass/fail observable.

**Missing piece.** A **permitted live confirmation session** — explicit owner
sign-off, since this switches real circuits. That permission gate, not
engineering, is the blocker.

**First three steps.**
1. Write the session plan: which Manual scene (pick the least-consequential
   circuit), expected ack (`code` 0 or 14), expected telemetry deltas, and
   abort criteria — file it through `renogy-change-control` for owner
   sign-off *before* touching anything.
2. With permission granted, run the scene from the HA button while capturing
   the RTM exchange (see `renogy-diagnostics-and-tooling` for capture
   tooling) and the resulting telemetry transitions.
3. Promote the label to `[CONFIRMED LIVE <date>]`, citing the capture:
   propose the §8.3 edit to the owner for the sibling's canonical
   `docs/PROTOCOL.md` (the sibling is read-only from HA sessions), and
   update this repo's bundled copy through `renogy-change-control` once it
   lands there.

**You have a result when** `docs/PROTOCOL.md` §8.3 carries
`[CONFIRMED LIVE <date>]` backed by a stored capture of a successful
`scene.run` with observed physical effect.

**Risks/obligations.** Hard gate: **no execution without explicit owner
permission** — this is the strongest unwritten rule in the project. If the
live run misbehaves, that is a finding for `renogy-failure-archaeology`, and
the Run button's availability should be reviewed, not papered over.

---

## Provenance and maintenance

- Authored 2026-07-12 against `ha-renogy-gateway` at commit `dc3c11f`
  (v0.5.1) and the read-only sibling `renogy-gateway` checkout. Every
  "current state" claim above was verified in source on that date; treat all
  of them as stale until re-checked whenever the manifest version moves.
- Web-sourced facts (all checked 2026-07-12): HACS default-store requirements
  (hacs.xyz publish docs), HA integration quality-scale tiers and manifest
  key (developers.home-assistant.io), brands image rules
  (home-assistant/brands README), and the Brands Proxy API for locally
  bundled custom-integration brands (HA developer blog, 2026-02-24). Re-verify
  before acting — HACS and quality-scale rules change.
- When an item lands: delete it from this file (do not mark it done and leave
  it), move any residual follow-ups into the relevant sibling skill, and note
  the removal date here.
- When adding an item: same discipline as above — verified current state,
  project-specific asset, first three file-level steps, falsifiable
  milestone, risks. No aspirations without a verification.
- Sibling skills own execution: `renogy-change-control` gates everything,
  `renogy-curation-parity-campaign` owns curation drift,
  `renogy-validation-and-qa` owns test gates.
