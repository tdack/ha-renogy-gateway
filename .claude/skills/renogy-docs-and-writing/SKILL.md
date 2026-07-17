---
name: renogy-docs-and-writing
description: >-
  House style and maintenance rules for the ha-renogy-gateway docs of record.
  Load when updating docs/PROTOCOL.md, CHANGELOG.md, README.md, CLAUDE.md, or
  strings.json; when writing commit messages; when documenting a new protocol
  finding or promoting a status label; when adding an evidence comment to a
  curated constant (e.g. api/discovery.py force-readonly entries); or when
  writing anything about this project for an external audience (issue replies,
  HACS listing text, brands PR).
---

# Renogy docs and writing

House style for `ha-renogy-gateway`'s documents of record, derived from the
repo's own examples. Write in British English throughout — the repo already
does ("Normalise milli-prefixed units", CHANGELOG 0.2.6). Use imperative voice
in commits and changelog bullets. "Sibling repo" below means `renogy-gateway`,
the canonical (private) TypeScript monorepo this integration was ported from.

## When NOT to use this skill

- **Release mechanics** (version bump order, tagging, CI, HACS validation) —
  see `renogy-run-and-operate`. This skill covers only what the changelog
  entry and docs must *say*.
- **Deciding whether evidence justifies a protocol-doc change** (what counts
  as a capture, how to analyse a HAR, when a live test is warranted) — see
  `renogy-analysis-and-evidence`. This skill covers how to *write it up* once
  the evidence exists.

## Doc inventory

| Document | Purpose | Update when | Consumers |
|---|---|---|---|
| `docs/PROTOCOL.md` | Reverse-engineered API/RTM spec; the "why we know this" record | A protocol finding is confirmed/refuted; a status label changes | AI sessions, debugging humans; linked from README |
| `CHANGELOG.md` | Notable changes per release | **Before every version bump/tag** — mandatory per `CLAUDE.md` | Users updating via HACS |
| `README.md` | User-facing install/config doc | Install flow, features, disclaimer, or branding changes | HACS renders it in-app (`hacs.json` sets `"render_readme": true`) and GitHub visitors |
| `CLAUDE.md` | Standing instructions for AI sessions | A new hard rule or workflow requirement emerges | Every future Claude session |
| `custom_components/renogy_gateway/strings.json` | HA UI strings (config flow, exceptions) | Config-flow steps/fields or raisable user-facing errors change | Home Assistant frontend |
| Evidence comments in code (notably `custom_components/renogy_gateway/api/discovery.py`) | Provenance for curated constants | Any curated entry is added or changed | Future maintainers deciding whether an override is still valid |

## PROTOCOL.md maintenance

### Provenance header and the sibling-canonical rule

This repo's `docs/PROTOCOL.md` is a carried-over copy of the canonical
document in the sibling `renogy-gateway` (TypeScript) repo. Its header says
so explicitly:

> **Note on this copy:** this document was carried over from the (private)
> TypeScript reference project this integration was originally ported from ...
> File-path references below (`packages/core/src/...`, ...) point at that
> project's structure, not at anything in this repo — they're kept as
> provenance for *why* a given protocol detail is known ...

**Workflow:** the sibling's `docs/PROTOCOL.md` is canonical, and the sibling
repo is read-only from HA sessions — protocol findings are PROPOSED to the
owner as a precise, evidence-cited edit to the sibling's copy; once landed
there, sync the bundled copy here. Never let this copy drift ahead of the
canonical one.
Keep the provenance header intact when syncing, and keep the sibling's
`packages/core/...`/`captures/...` path references verbatim — they are
provenance, not broken links to fix.

### Status legend and promotion rules

The legend (quoted from the doc):

> Status legend: **[confirmed]** seen in traffic · **[inferred]** strongly
> implied but not directly stated · **[untested]** not yet exercised live.

Rules:

- Every protocol claim carries a label, either on the section heading
  (`## 2. Auth (REST) — [confirmed]`) or inline on the specific claim.
- A label upgrades **only** with capture or live evidence — never from
  reasoning, docs elsewhere, or "it probably works". What qualifies as
  evidence is defined in `renogy-analysis-and-evidence`.
- Qualify the label when precision helps, as the doc already does:
  `[confirmed by live write tests]`, `[confirmed via captures]`,
  `[confirmed REST; execution path partly inferred]`,
  `[confirmed namespaces; full field list in captures]`.
- When a finding supersedes earlier text, say so rather than silently
  deleting: "(which tried refresh-token variants) is superseded by this
  finding."

### Dated-finding convention

Significant discoveries get a **date-stamped marker** (MM-DD), in bold,
placed on the heading or leading the paragraph. Real examples:

- `### 2.1 First-token bootstrap — [SOLVED 06-12]` — a previously-open
  question resolved.
- `**[confirmed 06-12]** The minted token lives **~7 days** ...` — a dated
  confirmation inline in a bullet.
- `**[CONFIRMED LIVE 06-14]** End-to-end cold start verified in production
  on a fresh Durable Object (empty token store, no seed).` — an end-to-end
  live verification, uppercase to flag the strongest evidence class.

Use `[SOLVED MM-DD]` for closing an open question, `[confirmed MM-DD]` for a
capture-backed detail, `[CONFIRMED LIVE MM-DD]` for behaviour exercised
against the real service. Include *what was observed* and *how* (which HAR,
which live run) in the surrounding prose.

### Section anatomy

Numbered `##` sections with `###` subsections (`§7.1` style cross-references
like "see §2.1" and "PROTOCOL.md §6"). Each section states the claim, its
status label, the concrete request/response shapes (endpoint, body, JWT
claims), and the failure modes observed (e.g. the exact error codes
`SYS003 "token can not null"`, `DMC400`). Tables for enumerable things
(hosts, op codes, connect-ack codes). Warnings inline with ⚠️.

## CHANGELOG.md style

Format observed across all entries:

- Heading: `## [X.Y.Z] - YYYY-MM-DD` (square-bracketed version, ISO date).
- Reverse-chronological; a short preamble at the top of the file only.
- Bullets only — no "Added/Fixed/Changed" subheadings.
- Bullet voice: **imperative verb first** ("Fix ...", "Add ...", "Retry ...",
  "Surface ...", "Stop persisting ...", "Normalise ...", "Port ...").
- Level of detail: one bullet carries **symptom + root cause + user impact**
  where relevant. Model entry (0.4.0):

  > Wire the RTM reader's unexpected-disconnect signal to the coordinator's
  > auto-reconnect logic — entities now correctly flip to `unavailable` on a
  > dropped WebSocket and recover automatically once it reconnects
  > (previously `schedule_reconnect()` was never invoked, so a dropped
  > connection was permanent until HA reloaded the integration).

  Pattern: *what changed* — *user-visible effect* — *(parenthetical: what was
  broken before and why)*.
- Backtick code identifiers (`gwm.get_product`, `battery_type`, `ops=7`);
  name concrete devices/pids when scoping a fix ("inverter pid `000F003C`").
- Notable = anything a user or downstream debugger would care about: fixes,
  new entities/features, behaviour changes, security changes (password no
  longer persisted, email redacted), and even CI fixes when they affected
  releases ("CI: don't run the Validate workflow on tag pushes"). Pure
  refactors with no observable effect are not listed.
- Per `CLAUDE.md`: the entry must exist and be committed **before or with**
  the version bump; never tag without one.

Fill-in template:

```markdown
## [X.Y.Z] - 2026-MM-DD

- <Imperative verb> <what changed> — <user-visible effect>
  (previously <symptom and root cause>).
- <Next notable change...>
```

## Commit message house style

Observed mix in `git log` (stated honestly):

- **Dominant recent pattern — conventional-commit style with scope**, used
  for all substantive changes since ~0.3.0:
  `fix(discovery): force charger.battery_type read-only on inverter pid 000F003C`,
  `feat(labels): port curated English labels + enum translation from core`,
  `test(sensor): confirm multi-namespace inverter device doesn't split across HA devices`,
  `fix(coordinator): non-destructive device merge on rediscovery`,
  `security(config): stop persisting account password + migrate`,
  `security(diagnostics): redact email`, `perf(discovery): dedupe concurrent
  get_model RPCs`, `docs: add HACS badge to README for easier integration access`.
- **Plain-sentence messages** for chores and older commits: `Bump to 0.5.1`,
  `Add CHANGELOG.md`, `Bundle protocol documentation locally`.

**Recommendation:** use the conventional pattern `type(scope): imperative
summary` for anything substantive. Types in use: `fix`, `feat`, `test`,
`docs`, `security`, `perf`. Scopes in use: `discovery`, `coordinator`,
`labels`, `sensor`, `rtm`, `config`, `diagnostics`. Version bumps stay plain
(`Bump to X.Y.Z`). Imperative mood, lowercase after the colon, no trailing
full stop.

## Evidence comments on curated code constants

Any curated override (force-readonly entry, label, enum curation) must carry
a comment block stating the **evidence** and **cross-references**. The
templates are the real blocks in
`custom_components/renogy_gateway/api/discovery.py`:

- Capture-cited, with the general rule and a concrete example
  (`_FORCE_READONLY_LEAVES`):

  > Matched case-insensitively: a real capture (captures/\*.har in the
  > sibling renogy-gateway repo) shows the same quantity under
  > inconsistently-cased leaf names on the same device (e.g. "voltage"
  > alongside "battery_input.Voltage") ...

- Live-schema-cited, quoting the observed `ops` value
  (`_FORCE_READONLY_SUFFIXES`):

  > Confirmed live in captures/\*.har: every lowercase "_today" daily
  > accumulator in the inverter's inverter_history model (...) reports
  > ops=[1,2,4,5,7] — the literal write bit genuinely present, despite being
  > a counter no one would ever "set".

- PROTOCOL-section-cited, explaining the scoping decision
  (`_FORCE_READONLY_LEAVES_BY_NAMESPACE`):

  > "state" is the real writable on/off field for distribution_box channels,
  > but PROTOCOL.md §6 documents tpms.tp_state_N.{...} as pure readings, and
  > on some rigs the schema marks several of them writable anyway (observed
  > live: pressure, online).

- Cross-repo parity note (`_FORCE_READONLY_LEAVES_BY_PID`, `battery_type`):

  > ... must match the equivalent pid-scoped fix in the sibling
  > renogy-gateway repo's packages/core/src/params.ts.

A new curated entry's comment must answer: what evidence (which capture,
live observation, or PROTOCOL §), why this scope (global vs namespace vs
pid), and what sibling-repo counterpart must stay in sync.

## strings.json

`custom_components/renogy_gateway/strings.json` holds config-flow UI strings
and exception messages. Structure maps 1:1 to `config_flow.py`:

- `config.step.user` / `select_gateway` / `reauth_confirm` correspond to
  `async_step_user`, `async_step_select_gateway`, `async_step_reauth_confirm`.
- Common HA strings use key references, not literals:
  `"email": "[%key:common::config_flow::data::email%]"`. Prefer these for
  standard fields/errors; write literals only for project-specific text
  ("The Renogy ONE Core gateway to integrate.").
- `config.error` keys (`cannot_connect`, `invalid_auth`, `unknown`) and
  `exceptions` keys (`cannot_connect`, `invalid_auth`, `update_failed`) must
  match the keys raised in code.

Update whenever a flow step, field, or user-facing exception is added or
renamed — hassfest CI validates this file.

## README conventions

- The **unofficial disclaimer** sits directly under the intro and must not
  be weakened. Current text (quote — keep or strengthen, never soften):

  > **Unofficial.** This integration talks to Renogy's private mobile-app
  > API, which has been reverse-engineered for interoperability and is not
  > publicly documented or supported by Renogy. It is not affiliated with or
  > endorsed by Renogy. The API can change without notice and break this
  > integration.

- HACS renders this README as the in-store page (`hacs.json`
  `"render_readme": true`), so it must stay accurate as an install document:
  the custom-repository steps, the My Home Assistant badge URL, and the
  config-flow walkthrough must match reality on every release.
- The README states the integration is **not in the default HACS store**; if
  that ever changes, rewrite the Installation section.
- **Icon / branding** section documents both delivery mechanisms (bundled
  `custom_components/renogy_gateway/brand/` served via the HA 2026.3+ Brands
  Proxy API, plus the `brands/custom_integrations/renogy_gateway/` staging
  copy ready for a home-assistant/brands PR) and credits the source
  (Renogy's own brand images via home-assistant/brands
  `custom_integrations/renogy/`). Keep the attribution if images change.

## External positioning

What may be said publicly (issue replies, listing text, blog-style posts):

- It is **unofficial**, reverse-engineered **for interoperability**, not
  affiliated with or endorsed by Renogy, and the API may change without
  notice and break it — i.e. exactly the README disclaimer, no more.
- **Never** claim or imply Renogy support, partnership, or approval.
- **Never** publish captures, HAR excerpts, tokens, dids, serial numbers,
  emails, or any account details — captures are gitignored evidence, not
  publishable material.
- Do not document behaviour as `[confirmed]` in any public text unless it
  has actually been capture- or live-confirmed per the promotion rules
  above; describe unverified behaviour as inferred/untested.
- **Open candidates (not done — label as such if mentioned):** submission to
  the default HACS store, and the home-assistant/brands PR (the staging copy
  under `brands/` exists for it). Present both as planned/possible, never as
  completed.
- Support posture: "a community project maintained on a best-effort basis"
  (README's own wording) — do not promise SLAs or Renogy escalation.

## Provenance and maintenance

- Authored 2026-07-12 for the ha-renogy-gateway skill library. Every style
  rule above is derived from, and quotes, actual repo content at v0.5.1:
  `docs/PROTOCOL.md` (header, legend, §2/§2.1 dated findings), `CHANGELOG.md`
  (entries 0.2.0–0.5.1), `git log` (through commit `dc3c11f`), `README.md`,
  `hacs.json`, `custom_components/renogy_gateway/strings.json`,
  `config_flow.py`, and `api/discovery.py` (force-readonly blocks).
- If the repo's real usage drifts from this document (new commit-type
  conventions, changed disclaimer, restructured changelog), the repo wins —
  update this skill from fresh examples rather than enforcing stale rules.
- If the HACS-store or brands-PR candidates land, update both the README
  conventions and External positioning sections here.
- Sibling skills: evidence standards live in `renogy-analysis-and-evidence`;
  release mechanics in `renogy-run-and-operate`; protocol content itself in
  `renogy-protocol-reference`.
