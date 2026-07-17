---
name: renogy-curation-parity-campaign
description: >
  Decision-gated campaign to detect, classify, and reconcile schema-curation
  drift between this HA integration and its canonical TypeScript sibling
  (renogy-gateway). Load when asked to check or reconcile curation drift, port
  sibling curation changes to HA, sync labels/options/readonly rules, audit
  parity between params.ts and discovery.py/const.py/labels.py, or when a
  field, switch, or setting surfaces differently between the dashboard and
  Home Assistant. Also load before any release if curation files changed in
  either repo since the last sync.
---

# Renogy curation parity campaign

The sibling repo `renogy-gateway` (TypeScript monorepo) is **canonical** for
curation: fixes land there first, or must be mirrored there. This HA port
copies its curation into Python constants, and those constants drift. This
skill is the executable campaign to measure that drift, classify every entry,
and reconcile it with evidence — never by guesswork.

**When NOT to use this skill:**
- You already know the single curation entry to add/change (e.g. "force
  `battery_type` read-only on pid X") → use `renogy-curation-and-flags` and
  its add-a-curation-entry checklist directly.
- You want to understand *why* a curation rule exists (its incident history)
  → `renogy-failure-archaeology`.
- The discrepancy is a protocol/decoding question, not a curation-constant
  question → `renogy-protocol-reference` / `renogy-debugging-playbook`.

## Ground rules (non-negotiable)

- **Sibling is canonical.** Never change curation semantics in HA alone; if
  the fix is genuinely new, it must be proposed for the sibling too.
- **Evidence bar:** captures, live observations, or a sibling commit that
  itself cites evidence. Never invent curation entries.
- **Never live-test writes** (op 1 / `async_write`) without explicit human
  permission. Curation work is read-and-constants work; it does not require
  writes.
- **This session cannot edit the sibling.** The sibling repo is read-only
  from HA sessions. Class-B items become written proposals for the owner, not
  commits.
- All ports go through `renogy-change-control` (changelog before version
  bump, per repo CLAUDE.md) and `renogy-validation-and-qa` (regression test).

## The curation axes (verified names, both repos)

| Axis | HA (this repo, `custom_components/renogy_gateway/`) | Sibling (canonical, `renogy-gateway/`) |
|---|---|---|
| Skip namespaces | `api/discovery.py` `_SKIP_NAMESPACES` | `packages/core/src/params.ts` `PARAM_HIDE_NS` |
| Force-readonly leaves | `api/discovery.py` `_FORCE_READONLY_LEAVES` | `packages/core/src/discovery.ts` `FORCE_READONLY_LEAVES` |
| Force-readonly suffixes | `api/discovery.py` `_FORCE_READONLY_SUFFIXES` | `packages/core/src/discovery.ts` `FORCE_READONLY_SUFFIXES` |
| Force-readonly by namespace | `api/discovery.py` `_FORCE_READONLY_LEAVES_BY_NAMESPACE` | `packages/core/src/discovery.ts` `FORCE_READONLY_BY_NS` |
| Force-readonly by pid | `api/discovery.py` `_FORCE_READONLY_LEAVES_BY_PID` | `packages/core/src/params.ts` `PARAM_FORCE_READONLY_BY_PID` |
| Hide leaves | `const.py` `HIDE_LEAVES` | `packages/core/src/params.ts` `PARAM_HIDE_LEAF` |
| Diagnostic patterns | `const.py` `_DIAGNOSTIC_PATTERNS` | `apps/hass-bridge/src/filter.ts` `DEFAULT_ENTITY_FILTER_CONFIG.diagnosticPatterns` |
| Instance patterns | `coordinator.py` `_INSTANCE_PATTERNS` | (no direct counterpart — HA-side entity naming) |
| Labels / options / zh | `api/labels.py` `LABELS`, `CURATED_OPTIONS`, `ZH_OPTION` | `packages/core/src/params.ts` `LABELS`, `CURATED_OPTIONS`, `ZH_OPTION` |
| Units / ordering / grouping | `sensor.py` `_UNIT_MAP` (units; no HA counterpart for ordering/grouping) | `params.ts` `UNIT_MAP` + `discovery.ts` `unitScale`; `LEAF_ORDER`, `NS_GROUP` |
| History metric allowlist | **no HA counterpart** (dashboard-only, see class D) | `packages/core/src/history.ts` `buildHistoryMetrics` (commit `824b83c`, 2026-07-06) |
| Write validation / caps | mirrored logic in `api/discovery.py` | `discovery.ts` `opsToCaps`, `validateWrite`, `withRetry`; `registry.ts` is an **offline fallback only**, never canonical |

Scope note: the two `PARAM_*` sets in `params.ts` curate the sibling's
**Settings/params list** (via `buildParams`), while HA's `_SKIP_NAMESPACES`
and `HIDE_LEAVES` gate **entity creation itself**. Same-named entries do not
always mean the same thing — this asymmetry drives class C below.

---

## PHASE 0 — Baseline: run the audit

The measurement tool is stdlib Python 3.10+, no deps:

```bash
python3 /path/to/ha-renogy-gateway/.claude/skills/renogy-diagnostics-and-tooling/scripts/curation_audit.py \
  /path/to/ha-renogy-gateway /path/to/renogy-gateway
echo "EXIT=$?"
```

Exit codes: `0` = no drift on strict axes, `1` = drift found, `2` = parse
failure.

**EXPECTED (observed by audit run on 2026-07-13; current-state as of
2026-07-12):** `EXIT=1`, **TOTAL DRIFT (strict axes): 8 entries**, all on the
`hide_leaves` axis:

- HA-only (6): `ai_count`, `dc_10a_count`, `dc_20a_count`,
  `dc_voltage_count`, `di_count`, `relay_count`
- TS-only (2): `state`, `ratio`

All force-readonly axes and `diagnostic_patterns` in parity (5/1/5/1 and 13
entries respectively, zero one-sided). The informational `skip_namespaces`
axis shows 6 TS-only namespaces (`alternator`, `battery_temp_sensor`,
`battery_volt_sensor`, `digital_input`, `inverter_history`, `signal`) — these
are Settings-list hides in the sibling, NOT discovery skips; they do not
count toward strict drift.

**Branches:**
- `EXIT=2` → the parser broke, most likely a sibling refactor renamed or
  moved a constant. Fix `curation_audit.py` first (it lives in
  `renogy-diagnostics-and-tooling`; skill files are editable). Re-verify the
  constant names against the table above with `grep -n` before touching the
  parser. Do not proceed on a broken instrument.
- `EXIT=0` → no strict drift. Record the date and audit output in your
  report, confirm the intentional-divergence list (Phase 2, class C) still
  matches what the script shows as one-sided-but-informational, and end the
  campaign.
- Drift on axes other than `hide_leaves`, or different `hide_leaves` entries
  → the world moved since 2026-07-12. Proceed, but **re-derive the
  classification table in Phase 2 from scratch**; do not assume the dated
  table below still holds.

---

## PHASE 1 — Sibling-side novelty scan

Drift the audit can see is only half the problem; the other half is sibling
curation the script does not yet parse. Scan sibling history since the last
sync (labels port `d98dfc5`, 2026-06-28, was the last curation sync — scan
from the day after, since a bare `--since` date is fuzzy about same-day
commits; adjust the date to the most recent sync commit you can identify):

```bash
git -C /path/to/renogy-gateway log --oneline --date=short --format='%h %ad %s' \
  --since=2026-06-29 -- \
  packages/core/src/params.ts packages/core/src/discovery.ts \
  packages/core/src/history.ts apps/hass-bridge/src/filter.ts
```

Verified output as of 2026-07-13 (newest first):

```
0d245da 2026-07-11 fix(core,dashboard): rescale milli-prefixed telemetry-history samples
824b83c 2026-07-06 fix(core): curate history metrics with an allowlist, not namespace membership
ffac2f3 2026-07-05 fix(params): exclude charger.battery_type from writable controls on inverter pid 000F003C
63380fb 2026-07-02 feat(core): add buildHistoryMetrics curated telemetry-history catalogue
30d3d9d 2026-06-30 fix(core): scale min/max bounds by unit prefix so they match normalised values
```

How to spot curation-relevant commits: subjects touching readonly rules,
hide/skip lists, labels, options, units, scaling of bounds, or allowlists.
Ignore pure plumbing (exports, migrations). For each candidate, `git -C
<sibling> show <hash>` and check whether HA has the equivalent. Known
worked example: `ffac2f3` was already ported to HA as `ae59831` (2026-07-05,
pid `000F003C` force-readonly) — the audit confirms that axis in parity.

**Known open items (verified 2026-07-13, no HA counterpart):**
- `LEAF_ORDER`, `NS_GROUP` in `params.ts` — the labels port (`d98dfc5`)
  took `LABELS`/`CURATED_OPTIONS`/`ZH_OPTION` only; display ordering and
  grouping have no HA counterpart. (`UNIT_MAP` is NOT open: HA's `sensor.py`
  `_UNIT_MAP` covers it — commits `4ae1191` 0.2.6 and `fcfceb4` 0.2.8.)
- `buildHistoryMetrics` allowlist (`history.ts`) — dashboard telemetry
  history; see class D.
- Bounds scaling (`30d3d9d`, `0d245da`) — check whether HA's number entities
  scale min/max by unit prefix the same way; if not, this is a class A
  candidate outside the audit's axes.

Build a candidate list: one row per item, with the sibling commit hash and
what evidence that commit cites.

---

## PHASE 2 — Classification gate (the decision core)

Classify **every** drift entry and every Phase 1 candidate into exactly one
class. Do not implement anything until the whole table is classified.

**Classification rules:**
- **(A) Genuine gap in HA — port to HA.** The sibling entry expresses a
  protocol/device truth (a leaf really is read-only, a label really is the
  device's name) and HA lacks it. Test: would an HA user see wrong behaviour
  (bogus writable control, raw Chinese label, mis-scaled bound) without it?
- **(B) Genuine gap in the SIBLING — propose porting there.** HA carries an
  evidence-backed entry the sibling lacks. You cannot commit to the sibling;
  write a precise proposal (constant, entries, evidence commit) for the
  owner.
- **(C) Intentional scope divergence — document and fence.** The same leaf
  name means different things because the constants gate different surfaces
  (HA: entity creation; TS: Settings list). Porting would break one side.
- **(D) Not applicable to HA.** Dashboard-only concerns. Record where it
  WOULD start to matter so a future session re-checks.

**Current entry table (as of 2026-07-12; re-derive if Phase 0 output
differs):**

| Entry / item | Class | Rationale |
|---|---|---|
| `ai_count`, `dc_10a_count`, `dc_20a_count`, `dc_voltage_count`, `di_count`, `relay_count` (HA-only hides) | **B** | HA commit `fcfceb4` (2026-06-27, "Audit full schema dump from captures; hide channel counts...") hid these bookkeeping leaves with capture evidence. The sibling's Settings list would benefit from the same hides. Propose adding to `PARAM_HIDE_LEAF`. |
| `state`, `ratio` (TS-only hides) | **C** | In TS these live in `PARAM_HIDE_LEAF`, which only prunes the **Settings/params list** built by `buildParams` — telemetry and channel controls are unaffected. In HA, `HIDE_LEAVES` gates **entity creation**: `state` is the on/off leaf behind every channel switch and `ratio` the dimmer level behind every light. Adding them to HA's `HIDE_LEAVES` would delete every switch and light entity. **Never port. Fenced.** |
| 6 TS-only `PARAM_HIDE_NS` namespaces (`alternator`, `battery_temp_sensor`, `battery_volt_sensor`, `digital_input`, `inverter_history`, `signal`) | **C** | Same scope asymmetry: TS hides them from Settings; HA's `_SKIP_NAMESPACES` would skip discovery entirely and delete their sensors. Informational axis in the audit; keep it that way. |
| `UNIT_MAP` / `LEAF_ORDER` / `NS_GROUP` | `UNIT_MAP`: covered in HA; `LEAF_ORDER`/`NS_GROUP`: **D (likely)** — verify | HA's `sensor.py` `_UNIT_MAP` already covers both sibling `UNIT_MAP` entries (`安培`→`A`, `℃`→`°C`) plus mV/mA/mW scaling — commits `4ae1191` (0.2.6) and `fcfceb4` (0.2.8). Residual gap: sibling `UNIT_FALLBACK` (unitless-leaf fallbacks) and keeping the two unit tables in sync when either side adds an entry. `LEAF_ORDER`/`NS_GROUP` are Settings-list display ordering/grouping; HA orders entities itself — likely D, confirm before closing. |
| `buildHistoryMetrics` allowlist (`824b83c`) | **D** | Dashboard telemetry-history storage curation. HA delegates history to its own recorder. WOULD matter if HA ever adds long-term-statistics curation or excludes noisy leaves from the recorder — re-check then. |
| Bounds scaling (`30d3d9d`, `0d245da`) | **A (candidate)** — verify first | If HA number entities take min/max straight from the schema without prefix scaling, users see wrong slider bounds. Confirm against `number.py`/discovery decoding before classifying finally. |

Gate rule: any entry you cannot confidently classify stays unclassified and
**blocks implementation of itself only** — classify and proceed with the
rest, and flag the stragglers to the owner. **Do not proceed past this gate
to implement A/B items whose evidence (Phase 3) you have not yet located.**

---

## PHASE 3 — Evidence obligation per class

- **Class A (port to HA):** re-verify the sibling's ORIGINAL evidence before
  porting — read the sibling commit message and anything it cites (a capture
  in `captures/`, a `docs/PROTOCOL.md` section, a live observation note).
  Never port blind: a sibling entry without traceable evidence gets queried
  with the owner, not copied. Method for reading captures/evidence →
  `renogy-analysis-and-evidence`.
- **Class B (propose to sibling):** cite this repo's history — the HA commit
  (e.g. `fcfceb4`) and the capture/schema-dump evidence it rested on. The
  proposal must let the owner apply it to the sibling without re-research.
- **Class C:** no code change; the obligation is documentation — the entry
  must appear in this skill's class-C table (or the successor table) with
  the mechanical reason porting breaks things.
- **Class D:** record the trigger condition under which it becomes relevant.

---

## PHASE 4 — Implementation and re-measurement

1. For each class-A item, follow the **add-a-curation-entry checklist in
   `renogy-curation-and-flags`** (constants file, regression test, changelog
   entry, evidence citation in the commit message). Do not restate or
   shortcut that checklist here.
2. For class-B items, write the sibling proposal (exact constant, exact
   entries, evidence refs) into your report for the owner. No sibling edits.
3. Re-run the Phase 0 command. **EXPECT:** every ported class-A entry gone
   from the drift report; class-C entries still present (they are the
   documented residue). Exit code goes to `0` only if all strict-axis drift
   was class A/B and the B items were accepted upstream — otherwise `1` with
   only documented class-C entries is the success state.
4. If the class-C list GREW (new intentional divergences), update the
   documented intentional-divergence table in this skill in the same change.
5. Release mechanics (version bump after changelog) → `renogy-change-control`
   and repo CLAUDE.md.

---

## Solution menu (ranked; all but 1 are candidates, not decisions)

1. **Periodic manual audit via `curation_audit.py`** — CURRENT PRACTICE.
   Cheap, proven. Obligation: someone must remember to run it; this skill is
   that reminder.
2. **Extend `curation_audit.py` to labels/units axes** (`LABELS`,
   `CURATED_OPTIONS`, `ZH_OPTION`, `UNIT_MAP`) — CANDIDATE. Obligation:
   TS-parsing robustness — these are `Record<string,string>` literals with
   unicode keys; the parser must not go exit-2 flaky on them.
3. **Shared machine-readable curation manifest** consumed by both repos —
   CANDIDATE / HEAVY. Obligation: design doc plus explicit owner sign-off,
   because it changes the sibling's architecture. Do not start this
   unilaterally.
4. **Scheduled CI audit job** — CANDIDATE. Obligation: decide where it runs;
   the sibling repo is private, so the job needs read access to both repos
   from wherever it lives.

---

## Fenced wrong paths (do not do these)

- **Porting TS-only `state`/`ratio` hides into HA's `HIDE_LEAVES`.** Kills
  every channel switch and dimmer entity (see class C). Same for the six
  TS-only `PARAM_HIDE_NS` namespaces into `_SKIP_NAMESPACES`.
- **Inventing curation without evidence.** No entry exists because it "seems
  diagnostic-ish". Captures/live observations or a cited sibling commit.
- **Hardcoding SKU or device-type roles.** Capabilities come from runtime
  discovery (`opsToCaps` / schema `ops`), never from SKU-prefix tables.
- **Treating `registry.ts` as canonical.** It is the offline fallback;
  runtime discovery is the source of truth.
- **Bypassing change control** — no version bump without a changelog entry;
  no port without a regression test.
- **Editing the sibling repo from this session.** Read-only. Class-B items
  are proposals, full stop.
- **Live-testing writes** to "confirm" a readonly classification without
  explicit human permission.

---

## Success metric

`curation_audit.py` exits `0` **modulo the documented intentional-divergence
list**, where every residual entry is itemised in the class-C table with a
mechanical rationale; and every port carries (a) evidence citation, (b) a
regression test, (c) a changelog entry. "Looks right" is never the bar.

---

## Provenance and maintenance

- Authored 2026-07-13 from a live audit run (exit 1, 8 strict entries, all
  `hide_leaves`) against HA `dc3c11f` (v0.5.1 era) and the sibling at
  `0d245da`. All constant names, file paths, and commit hashes in this skill
  were verified by grep/git against both working trees on that date.
- The Phase 0 EXPECTED block and the Phase 2 table are snapshots. When an
  audit run disagrees with them, the run wins: re-derive, then update this
  file (and the class-C table) in the same session.
- If `curation_audit.py` gains axes (solution 2) or the sibling refactors
  `params.ts`/`discovery.ts`, update the axis table here and re-verify the
  parser before trusting its exit code.
- Related skills: `renogy-curation-and-flags` (single-entry mechanics),
  `renogy-diagnostics-and-tooling` (owns the audit script),
  `renogy-analysis-and-evidence` (evidence method), `renogy-change-control`
  (release gates), `renogy-failure-archaeology` (why rules exist).
