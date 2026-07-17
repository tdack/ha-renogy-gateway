---
name: renogy-change-control
description: >
  Change classification, gates, and review rules for the ha-renogy-gateway
  Home Assistant integration. Load this BEFORE making any change to this repo:
  editing curation constants (force-readonly sets, hide lists, labels),
  touching the protocol layer (custom_components/renogy_gateway/api/),
  touching the control path (async_write, op-1 writes, scene.run), deciding
  whether a release or change is ALLOWED to ship (pre-merge gates, evidence
  bar, changelog-before-bump rule, CI green, regression-test requirement) —
  the approval policy; for step-by-step release commands use
  renogy-run-and-operate. Also load when asked "can I test this write live?", "how do releases work
  here?", "where does this fix belong — here or the sibling repo?", or when
  reviewing a diff for merge-readiness.
---

# Renogy change control — how changes are classified, gated, and reviewed

This skill is the written policy for changing `ha-renogy-gateway`, a HACS
custom integration (`custom_components/renogy_gateway/`, v0.5.1 as of
2026-07-12). Every rule below exists because something went wrong without it;
the incidents are cited so you understand *why*, not just *what*.

Jargon used throughout, defined once:

| Term | Meaning |
|---|---|
| **Sibling repo** | `renogy-gateway`, the private TypeScript monorepo (checked out as a sibling directory) this integration was ported from. It is **canonical** for protocol and curation behaviour. |
| **PROTOCOL.md** | `docs/PROTOCOL.md` in this repo — the reverse-engineered Renogy DC Home gateway API spec, bundled locally since v0.3.0. Section references (§2, §7.4, ...) point there. |
| **Capture** | A real Proxyman HAR of the Renogy phone app talking to the live rig, stored in the sibling repo's `captures/` (gitignored — contains credentials). The evidence bar for curation claims. |
| **op-1 write** | RTM WebSocket opcode 1 — a real control frame that switches physical circuits in the owner's home. |
| **Curation** | Hand-maintained constants that override or filter what runtime discovery reports: force-readonly sets, hide lists, curated labels/options. See the `renogy-curation-and-flags` skill for the full catalogue. |
| **sp** | Topic path — the `<did>/<namespace>.<field>` address of one field (the term `renogy-protocol-reference` uses). |

## The three unwritten rules, now written

1. **The sibling repo is canonical.** Protocol and curation fixes land in
   `renogy-gateway` (packages/core) first, or must be mirrored there. The
   sibling is READ-ONLY from HA sessions: "mirroring" means writing a
   precise, evidence-cited proposal for the owner (or confirming the
   counterpart already exists) — never committing to the sibling (see
   `renogy-curation-parity-campaign`). This repo *ports*; it never forks
   behaviour. The code
   already encodes this: `api/discovery.py` comments explicitly mirror
   `packages/core/src/params.ts` and `packages/core/src/discovery.ts`
   (e.g. `_parse_ops` "mirroring packages/core/src/discovery.ts's opsToCaps
   exactly"; the pid-scoped battery_type fix "must match the equivalent
   pid-scoped fix in the sibling renogy-gateway repo's
   packages/core/src/params.ts").
2. **Captures or live observations are the evidence bar.** No curation entry
   or force-readonly change ships without a real capture or live observation
   backing it. Never guess from the schema alone — the schema lies (it marks
   pure sensor readings writable; see §7.4 incidents below). Every existing
   curation constant in `api/discovery.py` carries a comment citing its
   capture evidence; new entries must too.
3. **Never test writes against the live rig without explicit human
   permission.** op-1 writes and `scene.run` switch real circuits in the
   owner's home. "Explicit" means the human said yes to *this specific
   write*, in this session, before you send it. No exceptions for
   "harmless-looking" fields, no toggling something back afterwards as a
   mitigation.

## Change classes and their gates

Classify every change before you start. A single PR may span classes — apply
the strictest applicable gate.

| Class | Examples | Gate |
|---|---|---|
| **(a) Curation** | Adding to `_FORCE_READONLY_LEAVES*`, `HIDE_LEAVES`, `_SKIP_NAMESPACES`, curated labels/options in `api/labels.py` | Capture or live-observation evidence, cited in a code comment; a written mirror proposal for the sibling's `packages/core/src/params.ts` (or confirm the counterpart already exists there — the sibling is read-only from HA sessions); regression test |
| **(b) Protocol layer** | `api/auth.py`, `api/rest.py`, `api/rtm.py`, `api/discovery.py`, `api/models.py` behaviour | Must match PROTOCOL.md and the sibling core's implementation; if PROTOCOL.md is wrong or incomplete, update this repo's copy alongside the code and write a proposal for the sibling's canonical copy (read-only from here) |
| **(c) HA layer** | Entity platforms, config flow, coordinator wiring, diagnostics | Normal review + tests green; follow HA custom-integration conventions; no protocol assumptions smuggled in |
| **(d) Control path** | `coordinator.async_write`, `_validate_write_value`, `button.py` (scene run), anything that can emit op-1 or `scene.run` | Strictest gate: all of (b), plus **explicit human permission before any live write test**. Schema validation must stay intact (existence, writability, type, bounds, `ctrl_sp_blacklist`) |
| **(e) Release** | Version bump + tag | Release gate below; CI green first |

When in doubt whether something is curation vs protocol: if it changes *which
fields exist / how they decode*, it is protocol; if it changes *which of the
discovered fields are surfaced, writable, or labelled*, it is curation.

### Class (a) curation — the sanctioned exception to discovery-over-hardcoding

The project's prime directive (from the sibling repo's brief) is
discovery-over-hardcoding: device types, channels, units, and controllability
come from runtime discovery, never literals. Curation constants are the one
sanctioned exception, allowed **only** because the schema is demonstrably
wrong in specific, capture-proven ways. That is why the evidence bar exists:
an uncited curation entry is indistinguishable from the hardcoding the
project forbids. The catalogue of existing constants and their evidence
lives in the `renogy-curation-and-flags` skill; the campaign to keep them in
lockstep with the sibling repo is `renogy-curation-parity-campaign`.

### Class (d) control path — what "permission" looks like

Before any live write during development or debugging:

1. State exactly what you intend to write: the sp, the value, the expected
   physical effect ("this will turn off the bedroom light circuit").
2. Wait for the human to approve that specific write.
3. Log the write and its ack. `async_write` already warns on unexpected ack
   codes (anything other than 0 or 14) — keep that.

Prefer non-live verification wherever possible: unit tests against captured
frame shapes, dry-run assertions that the validator rejects bad values.
Reading and subscribing are always safe; only op-1 and scene execution are
gated. Note PROTOCOL.md §8.3: `scene.run` is "model confirmed; run untested
live" (as of 2026-07-12) — treat live scene execution as a first-time write
experiment requiring permission.

## The release gate (class e)

From `CLAUDE.md` (repo root), verbatim policy: update `CHANGELOG.md` with an
entry for the new version **before** bumping the version in
`custom_components/renogy_gateway/manifest.json` and tagging; commit the
changelog update along with (or just before) the version bump commit; never
tag without a changelog entry.

The observed release pattern in `git log` (verified 2026-07-12) is:

```
fix/feat commits (each fix paired with its regression test)
  → one "Bump to N.N.N" commit touching CHANGELOG.md + manifest.json together
  → tag vN.N.N
```

Examples: v0.5.1 = `d11f43e` (regression test) + `ae59831` (fix) →
`1f81c68` "Bump to 0.5.1" (CHANGELOG.md + manifest.json in one commit) →
tag `v0.5.1`. Same shape for v0.5.0 (`b3eec58`). The 0.4.0 bump (`012f883`)
predates the changelog and touched only manifest.json — `CHANGELOG.md`
(`b189393`) and the CLAUDE.md rule (`d9790a6`) were added immediately after,
which is *why* the rule exists. Do not repeat that shape.

Versioning is `0.MINOR.PATCH` on `manifest.json`'s `version` field; tags are
`vN.N.N` (fourteen tags v0.2.0 → v0.5.1 as of 2026-07-12).

## The regression-test norm

Fixes ship with a regression test in the same release. This is the observed
norm, not aspiration:

- v0.3.0: `46e3cb4` "Add regression test for tank ratio/connected
  classification" accompanying the TPMS/tank fixes of the 0.2.x line.
- v0.5.1: `d11f43e` "test(sensor): confirm multi-namespace inverter device
  doesn't split across HA devices" landed alongside the `battery_type`
  force-readonly fix `ae59831`.
- v0.4.0: the password-removal commit `7a864fa` itself included
  `tests/test_config_flow.py` and `tests/test_init.py` changes (migration
  coverage) in the same commit.

Rule: if you fixed a behaviour, add a test that fails without the fix. The
test suite is `tests/` (pytest-homeassistant-custom-component; see
`renogy-build-and-env` for how to run it — it needs Python 3.13).

## Non-negotiables, each with its incident

| Rule | Incident behind it |
|---|---|
| **Never persist the account password.** Config entries store tokens only; a `TokenSet` is refreshed via callback. | Early versions stored the password in the config entry. Removed in v0.4.0, commit `7a864fa` "security(config): stop persisting account password + migrate" — existing entries are migrated to drop it. Do not reintroduce it, including in diagnostics or logs (the login sends it cleartext over TLS; never log request bodies). |
| **Never derive writability by OR-ing `ops` ints.** `ops` on the wire is a list of enum codes {1,2,4,5,7}; 5 and 7 mean "read + subscribe", and write is contributed ONLY by a literal `1` in the list. | Bit this project **twice** (v0.2.3's path-pattern band-aid, root-caused in v0.2.4 commit `831cd77`; residual decomposition bug fixed in v0.2.7 commit `b1d260e`). PROTOCOL.md §7.4 documents it; `_parse_ops` in `api/discovery.py` implements it with the full war story in its docstring. Naive OR-ing surfaced TPMS pressure, shunt SOC, tank ratios, and energy counters as writable Number/Select entities. |
| **Always persist rotated tokens, atomically and immediately.** | PROTOCOL.md §2: refresh tokens rotate on every refresh and the old one dies — failure to persist the new pair locks the account out of API access. `api/auth.py` enforces this via the mandatory `on_token_refresh` callback; any change to auth must keep that invariant. Treat HTTP 401 **and 999** as refresh triggers (`api/rest.py` already does). |
| **Discovery over hardcoding.** No SKU-prefix role detection, no channel-name tables, no controllable allowlist. | The founding rule of the sibling repo's brief: a new, rewired, or unfamiliar rig must work with no code edits. Curation constants (class a) are the only sanctioned, evidence-backed exception. |
| **int64 DIDs travel as strings (`did_str`).** | Device IDs are 64-bit integers that exceed JavaScript's 53-bit safe-integer range; the canonical TypeScript core must carry them as strings, so this port does too for parity and JSON safety. `models.py` keeps `did_str: str` on `GatewayInfo`/`RenogyDevice`, with a `did` property for lossless int conversion when Python needs the number. Never round-trip a DID through a float or a JS-shaped JSON layer as a number. |
| **Redact credentials and email in diagnostics.** | v0.4.0 commit `73ee0a6` "security(diagnostics): redact email" — `diagnostics.py` keeps a `_REDACT` set and substitutes `**REDACTED**`. Any new field added to config entry data must be assessed for redaction. Captures also contain credentials — never commit them anywhere. |

## CI gates — what must be green

Two workflows in `.github/workflows/` (verified 2026-07-12):

| Workflow | Jobs | Triggers |
|---|---|---|
| `test.yml` ("Test") | `pytest` on Python **3.13**, deps from `requirements_test.txt` (`pytest-homeassistant-custom-component`, `pytest-asyncio`) | every push and pull_request |
| `validate.yml` ("Validate") | `hassfest` (home-assistant/actions/hassfest) and `hacs` (hacs/action, category: integration) | pushes to **branches: main only**, pull_request, weekly cron, manual dispatch |

All three checks (pytest, hassfest, hacs) must be green before merge and
before tagging.

**Known quirk:** Validate deliberately skips tag pushes (commit `8db60f6`)
— do not "fix" it by re-widening the trigger. Operational detail →
`renogy-run-and-operate`; incident history → `renogy-failure-archaeology`.

## Pre-merge checklist

Run through this before merging any change:

```text
[ ] Change classified (a-e above); strictest applicable gate identified
[ ] Curation change? -> capture/live evidence cited in a code comment,
    AND a written mirror proposal for sibling packages/core/src/params.ts
    (or counterpart confirmed present) — the sibling is read-only from here
[ ] Protocol change? -> matches docs/PROTOCOL.md; this repo's copy updated,
    and a proposal written for the sibling's canonical copy if the protocol
    understanding changed
[ ] Control-path change? -> schema validation intact (existence, writable,
    type, min/max, ctrl_sp_blacklist); NO live write was tested without
    explicit human permission
[ ] Regression test added that fails without the fix
[ ] No password persisted or logged; no new unredacted PII in diagnostics
[ ] No ops OR-ing; writability only from literal code 1 (via _parse_ops)
[ ] DIDs still strings end-to-end (did_str)
[ ] Token rotation persistence untouched or strengthened
[ ] pytest green on Python 3.13 (locally or via CI)
[ ] hassfest + HACS validation green (CI on the branch push / PR)
```

## Release checklist

```text
[ ] All intended fixes merged, each with its regression test
[ ] CI fully green on main (Test + Validate)
[ ] CHANGELOG.md: add a "## [N.N.N] - YYYY-MM-DD" section summarising
    notable changes since the previous tag (match the existing entries' voice)
[ ] Bump "version" in custom_components/renogy_gateway/manifest.json
[ ] Commit changelog + bump together as "Bump to N.N.N"
    (or changelog commit immediately before the bump commit — never after)
[ ] Annotated tag vN.N.N on the bump commit; pushing the tag is the
    publish action (HACS reads releases from tags)
[ ] Do NOT expect Validate to run on the tag push — that is intentional
    (commit 8db60f6; see renogy-run-and-operate)
```

Step-by-step commands (annotated tag, stop-before-push): →
`renogy-run-and-operate`.

## When NOT to use this skill

- **What a curation constant means or which fields are curated** — see
  `renogy-curation-and-flags` (the catalogue) and
  `renogy-curation-parity-campaign` (keeping parity with the sibling repo).
- **Protocol frame shapes, auth flow, opcode semantics** — see
  `renogy-protocol-reference` (and `docs/PROTOCOL.md` itself).
- **How the layers fit together / where code belongs** — see
  `renogy-architecture-contract`.
- **Running the test suite, Python 3.13 setup, dev environment** — see
  `renogy-build-and-env`; broader QA strategy is
  `renogy-validation-and-qa`.
- **Diagnosing a live bug** — see `renogy-debugging-playbook`; past
  incidents in depth are `renogy-failure-archaeology`.
- **Operating a running install, diagnostics dumps** — see
  `renogy-run-and-operate` and `renogy-diagnostics-and-tooling`.
- **Analysing captures / gathering evidence** — see
  `renogy-analysis-and-evidence`; open unknowns are
  `renogy-research-frontier`.
- **Writing docs or changelog prose style** — see `renogy-docs-and-writing`.

## Provenance and maintenance

All facts verified against the repo on 2026-07-12. Re-verify anything that
may have drifted (run from the `ha-renogy-gateway` repo root):

```bash
# Current version (skill says 0.5.1)
grep '"version"' custom_components/renogy_gateway/manifest.json
# Release pattern and cited commits still as described
git log --oneline | head -20 && git tag
git show --stat --oneline 1f81c68 7a864fa 73ee0a6 8db60f6 | grep -E '^[0-9a-f]{7} '
# Changelog-before-bump policy unchanged
cat CLAUDE.md
# CI: Python version, triggers, Validate's main-only push scope
cat .github/workflows/test.yml .github/workflows/validate.yml requirements_test.txt
# ops-is-not-a-bitmask doctrine and its capture evidence
grep -n 'literal' docs/PROTOCOL.md | head; sed -n '/def _parse_ops/,+15p' custom_components/renogy_gateway/api/discovery.py
# Curation constants and their evidence comments
sed -n '20,130p' custom_components/renogy_gateway/api/discovery.py
# Control-path validation still intact
grep -n -A 25 'async def async_write' custom_components/renogy_gateway/coordinator.py
# Token rotation invariant
grep -n -B2 -A4 'on_token_refresh' custom_components/renogy_gateway/api/auth.py | head -20
# DIDs as strings
grep -n 'did_str' custom_components/renogy_gateway/api/models.py
# Diagnostics redaction
grep -n -A5 '_REDACT' custom_components/renogy_gateway/diagnostics.py
# scene.run still untested live? (update the class-d note if this changes)
grep -n 'run untested live' docs/PROTOCOL.md
```
