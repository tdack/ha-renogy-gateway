---
name: renogy-analysis-and-evidence
description: >-
  Proof-and-analysis methodology for the Renogy DC Home reverse-engineering
  projects (ha-renogy-gateway and the sibling renogy-gateway). Load this when
  establishing a protocol fact, validating a hypothesis about device or schema
  behaviour, mining a HAR capture, planning a live read-only probe, deciding
  whether the evidence justifies a code or curation change, or promoting a
  PROTOCOL.md status label ([untested] -> [inferred] -> [confirmed]). Covers
  the evidence bar, source ranking, the idea lifecycle, HAR mining, ops-enum
  proofs, hypothesis-driven probing, differential schema analysis, and
  negative-result archaeology.
---

# Renogy analysis and evidence

Methodology for proving things about Renogy's *private* DC Home gateway API.
There are **no public docs** for this API. Every fact in `docs/PROTOCOL.md`
was earned from captured traffic, live probes, or cross-referencing the
official app's behaviour — and every future fact must be earned the same way.
The motto: **prove it, don't just install it.**

## When to use this skill

- You are about to assert something new about the protocol, a device schema,
  or field semantics.
- You have a hypothesis ("this field is really read-only", "this endpoint
  mints tokens") and need to test it properly.
- You are deciding whether observed evidence justifies a code change, a
  curation entry, or a PROTOCOL.md status-label promotion.
- You need to mine a Proxyman HAR or plan a live probe.

## When NOT to use

- **Routine debugging** of a failing integration (entity missing, reconnect
  loop, bad state) → `renogy-debugging-playbook`.
- **Looking up a settled finding** (what did we conclude about `coef`?) →
  `renogy-failure-archaeology` and `docs/PROTOCOL.md` directly.
- **Reconciling curation drift** between core, dashboard, and the HA
  integration → `renogy-curation-parity-campaign`.

## Repos and ground truth

- `ha-renogy-gateway` — the HA custom integration (primary working repo).
- `renogy-gateway` (sibling, **canonical**, read-only from HA sessions) —
  `captures/` (Proxyman HARs, **contain credentials — never quote tokens or
  passwords**), `reference/renogy_client.py`, `scripts/` probes, and the
  superset `docs/PROTOCOL.md`.
- Both repos carry a `docs/PROTOCOL.md` with the status legend:
  **[confirmed]** seen in traffic · **[inferred]** strongly implied but not
  directly stated · **[untested]** not yet exercised live. Saga findings get
  dated tags: `[SOLVED 06-12]`, `[CONFIRMED LIVE 06-14]`.

---

## 1. The evidence bar (doctrine)

Hold every proposed fact to all four tests before it goes anywhere near
PROTOCOL.md or the codebase:

1. **One mechanism must explain ALL observations — including the negatives.**
   A theory that explains why writable fields work but not why read-only
   fields also *appear* writable is a symptom patch, not a finding. (See the
   ops-enum recipe below: the winning explanation covered both
   `Bat_Chg_Energy` being read-only *and* `dc_output_ext.state` being
   writable with one rule.)
2. **A hypothesis must predict specific values BEFORE testing.** Write down
   what you expect to see (exact error code, exact ops list, exact payload
   shape) before you open the HAR or run the probe. If you only decide what
   counts as confirmation after seeing the data, you have confirmed nothing.
3. **A finding must survive adversarial refutation.** Actively hunt the
   counterexample: grep every capture for the case that would break your
   rule. The ops-enum fix was only trusted after searching for a `[2,4,5,7]`
   field that *was* writable (none found) and a `[1,...]` field that was not
   (found — which revealed a second, real phenomenon; see recipe 2).
4. **The schema's own claims are NOT evidence.** `get_model` lies —
   PROTOCOL.md §7.7 catalogues confirmed lies (write code `1` on `_today`
   counters that nobody can set, Chinese unit strings, `coef` that must not
   be applied, identically-named fields with different `ops` across
   namespaces). Schema self-description is a *hypothesis generator*, never a
   proof.

### Source ranking

| Rank | Source | Notes |
|---|---|---|
| Gold | Live capture of the official app (Proxyman HAR) | What the app actually sends/receives is definitive. |
| Silver | Live read-only probe (op 2 / op 4 / op 6) | Requires explicit owner permission — see recipe 5. |
| Bronze | Cross-referencing the app's own curation behaviour | e.g. "the app never renders a control for X" implies X isn't meant to be writable. Circumstantial but real. |
| Unranked | Schema self-description alone | Unreliable — §7.7. Corroborate or discard. |

A claim backed only by bronze or below stays **[inferred]** at best.

---

## 2. The idea lifecycle

Every protocol idea moves through these stages. Do not skip stages, and do
not let an idea live in your head — write it down at the hypothesis stage.

1. **Hunch** — a capture curiosity, an app-behaviour mismatch, an HA user
   symptom. (Historically, all three have produced real findings.)
2. **Hypothesis with predicted observations** — state it falsifiably: "if
   refresh-token can cold-mint, then posting `{}` should return a token, not
   an error."
3. **Evidence** — HAR mining (recipe 1) or a permitted probe (recipe 5).
4. **PROTOCOL.md entry** — with the correct label and, for sagas, a dated
   tag. Propose the update to the *sibling's* PROTOCOL.md (canonical; the
   sibling is read-only from HA sessions — write the exact diff for the
   owner), then sync the HA repo's bundled copy once it lands.
5. **Implementation + regression fixture** — the code change lands with a
   test pinning the evidence (e.g. HA commits `d11f43e` pin multi-namespace
   inverter grouping; `46e3cb4` pins tank ratio/connected classification).
6. **Changelog** — the HA repo's `CLAUDE.md` requires a `CHANGELOG.md` entry
   before any version bump/tag.

### Label promotion rules

- **[untested] → [inferred]**: consistent indirect evidence — multiple
  captures agree, or the app's behaviour implies it, but you never saw the
  exact exchange.
- **[inferred] → [confirmed]**: seen in real traffic, or observed in a
  permitted live session. Date-stamp significant confirmations
  (`[CONFIRMED LIVE 06-14]`).
- Never promote on schema say-so alone (evidence-bar test 4).

### Retirement path

Superseded findings **stay inline with corrections** — do not delete history,
annotate it. Real example: PROTOCOL.md §2.1 keeps the failed refresh-token
investigation visible and states that `scripts/probe-rtm-bootstrap.ts`
"(which tried refresh-token variants) is superseded by this finding". A
future session that re-derives the dead idea hits the correction instead of
re-fighting the war. Likewise §2 corrects the token-lifetime belief in place:
"~7 days (not ~2082 as previously thought)".

---

## 3. Recipes

Each recipe is a numbered procedure plus a worked example from this project's
real history (verified in git/docs, 2026-07-12).

### Recipe 1 — HAR capture mining

The gold-standard source. HARs live in the sibling's `captures/` (gitignored;
see `captures/README.md`).

1. **Credential hygiene first.** Every HAR contains the account password in
   cleartext (login body) and live JWTs. Never quote tokens, passwords, or
   `x-token`/`device-token` header values in any output, doc, or commit.
   Redact before pasting anything.
2. **Know the HAR shape.** A HAR is JSON: `log.entries[]`, each with
   `request.{method,url,headers[],postData.text}` and
   `response.{status,content.text}`. WebSocket frames (Proxyman export)
   appear as `_webSocketMessages` on the upgrade entry.
3. **Index the traffic** before diving in:
   ```sh
   python3 -c "import json,sys; \
     [print(e['request']['method'], e['request']['url'], e['response']['status']) \
      for e in json.load(open(sys.argv[1]))['log']['entries']]" captures/<file>.har
   ```
   or `jq -r '.log.entries[] | "\(.request.method) \(.request.url) \(.response.status)"' <file>.har`.
4. **Extract the pair you care about.** Filter by URL substring, then print
   `postData.text` and `response.content.text`; `json.loads` the bodies
   (JSON-in-a-string). For RTM material (`get_model` schemas, `ops` arrays,
   `userdata_str.config` payloads), search the WebSocket messages for the
   method name and pair request/response by `id`.
5. **Hunt the counterexample** (evidence-bar test 3): once you think you see
   a pattern, grep *all* the HARs for the case that would break it before
   writing anything down.

**Worked example — the real shape of `userdata_str.config`** (sibling commit
`626c809`, 2026-06-27). PROTOCOL.md originally described the channel-label
map as a flat `{channel: label}` string map. While porting to
ha-renogy-gateway, mining the real payload in `captures/*.har` falsified
that: the confirmed shape is **namespace-qualified keys**
(`"distribution_box.dc_10a_1"`) with **object values** (a ChannelConfig:
`name`/`channelEnable`/`controlMode`/`icon`/...), and an unset name reads
back as the literal placeholder `"--"`, not as absent. A port taking the doc
at face value (filtering for string values) "would silently apply zero
channel labels, ever" — the very bug fixed in the HA repo at `a6b0e7f`
(0.2.9, "Fix user channel labels never applying"). The doc was corrected in
place in §5/§7.5. Lesson: even our *own* docs are hypotheses until re-checked
against a capture.

### Recipe 2 — The ops-enum proof (the canonical full-bar example)

How to tell a symptom patch from a root-cause finding. Follow this pattern
whenever "the code misclassifies X" appears.

1. **State the symptom precisely.** Which fields, which classification, on
   which device.
2. **Reject fixes that only explain the positives.** If your fix is a list of
   known-bad paths, you have described the symptom, not the mechanism.
3. **Find discriminating evidence** — a minimal pair where the proposed
   mechanism predicts opposite outcomes; check both against captures.
4. **Implement the mechanism, delete the band-aid.** The band-aid's continued
   existence hides future counterexamples.
5. **Re-run the adversarial hunt.** Surviving exceptions are not noise — they
   may be a *second real phenomenon* needing its own mechanism.

**Worked example** (HA repo, June 2026):

- *Symptom:* genuinely read-only readings (TPMS pressure, shunt SOC) surfaced
  as writable Configuration Number entities.
- *Wrong fix #1:* 0.2.3 (`4108f95`) forced "well-known telemetry paths"
  read-only via a hardcoded path-pattern list ported from
  `apps/hass-bridge/src/filter.ts` — a tool built for MQTT publish
  inclusion, not classification. It explained nothing; it suppressed the
  visible cases.
- *Discriminating evidence:* PROTOCOL.md §7.4 — `ops` is a small **enum**
  `{1,2,4,5,7}`, not an OR-able bitmask. `5` and `7` are composite codes
  meaning "read + subscribe" and do **not** imply write despite `5 == 4+1`
  in binary. The minimal pair from captures: `inverter_history.Bat_Chg_Energy`
  reports `ops:[2,4,5,7]` (no literal `1`) and is genuinely read-only, while
  `dc_output_ext.state` reports `ops:[1,2,4,5,7]` (literal `1` present) and
  is genuinely writable. One rule — *write ⇔ literal `1` in the list* —
  explains the positive AND the negative case.
- *Root-cause fix:* 0.2.4 (`831cd77`) rewrote `_parse_ops` to match
  `packages/core/src/discovery.ts`'s `opsToCaps` and **deleted the
  path-pattern band-aid** — "the dashboard has no such list; it doesn't need
  one once ops is parsed correctly". (The bug bit twice: 0.2.7 `b1d260e`
  found the fix had special-cased `5` but not `7`, so `[2,4,5,7]` still set
  the write bit via the literal `7`.)
- *The residual exceptions:* the adversarial hunt then found fields carrying
  a **genuine literal `1` that still must not be writable** — the lowercase
  `_today` daily accumulators in `inverter_history` report `ops:[1,2,4,5,7]`
  despite being counters nobody can set (their PascalCase `_Total` siblings
  correctly report `[2,4,5,7]`). That is the schema *lying* — a second
  phenomenon, handled by a second mechanism: force-readonly curation
  (sibling `84856f2`, findings recorded in `f282e53`, catalogued in
  PROTOCOL.md §7.7).
- *Lesson:* "one mechanism explains all observations" sometimes resolves into
  discovering there are **two phenomena** — correct ops parsing AND a small
  confirmed-liar list. Both are principled; the path-pattern list was not,
  because it conflated them.

### Recipe 3 — Hypothesis-driven probing (the cold-boot bootstrap saga)

Use when a protocol question can't be answered from existing captures and
each candidate answer predicts a distinguishable response.

1. **Enumerate the candidate mechanisms.** For each, write the exact request
   variant and the response that would confirm or falsify it.
2. **Probe the variants** (read-only / harmless endpoints only; permission
   per recipe 5). Record every response verbatim — error codes are data.
3. **When all variants die, the falsifications narrow the space.** Go get
   the discriminating capture.
4. **Confirm live, then date-stamp.**

**Worked example — how does a fresh install get its first rtmToken?**
(PROTOCOL.md §2.1, `[SOLVED 06-12]`, `[CONFIRMED LIVE 06-14]`):

- *Candidates:* `refresh-token` with some special body. Probed variants
  (`scripts/probe-rtm-bootstrap.ts`): `{}`/`null` → `SYS003 "token can not
  null"`; `{"token":""}` → 500 `SYS001`; account access/refresh tokens →
  `DMC400 "User data anomaly detected"`. Every variant falsified —
  refresh-token is rotation-only.
- *Pivotal evidence:* a **genuine** cold-boot HAR (new device, no keychain,
  manual login) showed `do_login` → `POST /api/v2/device/app-register`
  (`{pid:"003F0000", sn:"<device_uuid>#<email>", nodeType:4}`) → `/rtm/ws`
  101. The earlier "reinstall" capture had misled — the iOS keychain
  persists the device_uuid + token across reinstalls, so it was never a
  cold boot. Check that a capture actually represents the state you think
  it does.
- *Confirmation:* `[CONFIRMED LIVE 06-14]` — a fresh Durable Object with an
  empty token store onboarded with only email + password, minted via
  app-register, and streamed live telemetry; the seed-token path became an
  optional override.
- *Retirement:* §2.1 notes the probe script "is superseded by this finding";
  the probe stays in `scripts/` as a methodological model.
- *Reusable for:* any auth/session question — enumerate, predict error codes,
  falsify, then capture the real flow.

### Recipe 4 — Differential schema analysis

When you can't capture the behaviour directly, triangulate by comparing the
same field across namespaces, product ids, or rigs. Divergence between
"identical" things is how schema lies surface.

1. Pull `get_model` for every namespace that carries the field (from HARs or
   the cached registry).
2. Diff the field entries: `ops`, `type`, `unit`, bounds, `options`.
3. Where they disagree, decide which side reality is on using higher-ranked
   evidence (does the app render a control? does a probe read succeed?).
4. Record the deviation in §7.7 and defend against it in code (curation
   override) — never by "fixing" the schema mentally.

**Worked examples** (all recorded in PROTOCOL.md §7.7):

- `charger.desired_voltage`/`desired_current` report `ops:[1,2,4,5,7]`
  (writable — a genuine setpoint), while `start_battery.desired_voltage`/
  `desired_current` report `[2,4,5,7]` — the same conceptual setting, never
  marked writable for that sub-feature. Same name ≠ same capability.
- TPMS `tp_state_N.{pressure,online,state}` carry the write code on **some
  rigs** — not reproduced in this account's captures but reported live.
  Cross-rig comparison catches what one account's captures cannot.
- `charger.battery_type` on the inverter pid `000F003C` is schema-writable
  but was force-curated read-only (sibling `ffac2f3`, HA `ae59831`) —
  per-*pid* divergence of an identically-named field.

### Recipe 5 — Live read-only probing protocol

Live probes are silver-tier evidence but use the owner's real account and
touch a real power system. Discipline:

1. **Permitted instruments:** op 2 (read), op 4 (subscribe), op 6 (RPC gets —
   `gwm.devs`, `gwm.get_product`, `gwm.get_model`). Read-only.
2. **NEVER without explicit human permission:** op 1 (`write` — it switches
   physical circuits) and `scene.run`. And because even *read-only* probes
   use the owner's credentials and open a live session, **ask before any
   live session at all**. If a write is ever authorised, validate against
   the schema and honour `driving_mode.ctrl_sp_blacklist`.
3. **Model your probe on the sibling's scripts:**
   `scripts/probe-rtm-bootstrap.ts` and `scripts/probe-inverter-schema.ts`.
   Note the latter was committed *unrun* — "not yet run — needs shore power"
   (sibling `4d4b418`). Even a read probe waits for the rig conditions that
   make its answer meaningful.
4. **Logging discipline:** record raw frames verbatim (redacting tokens);
   note the rig state at probe time (shore power? charging? which devices
   online?) — a reading without its context cannot be re-interpreted later.
5. **Write the finding up immediately** with a dated tag while the session
   context is fresh.

### Recipe 6 — Negative-result archaeology (the anti-re-fighting rule)

**Before ANY protocol investigation**, check whether it has already been
fought. Superseded ideas are documented inline precisely so you find them.

1. Grep the canonical protocol doc:
   ```sh
   grep -n -i "<topic>" docs/PROTOCOL.md          # in renogy-gateway (canonical)
   grep -n "superseded\|SOLVED\|CONFIRMED LIVE" docs/PROTOCOL.md
   ```
2. Grep both repos' history — commit messages here are unusually rich (they
   record evidence, falsified alternatives, and wrong fixes):
   ```sh
   git -C <renogy-gateway> log --all -i --grep="<topic>" --oneline
   git -C <ha-renogy-gateway> log --all -i --grep="<topic>" --oneline
   git -C <repo> log -S "<identifier>" --oneline    # code archaeology
   ```
3. Check the sibling's `scripts/` for an existing probe and both
   `CHANGELOG.md`s for the fix history before designing a new experiment.
4. If prior art exists and was falsified, stop — unless you hold *new*
   evidence the old sessions lacked.

**Worked example:** the refresh-token cold-mint idea is permanently dead —
§2.1 and the superseded `probe-rtm-bootstrap.ts` record exactly which
variants were tried and which error codes killed them (`SYS001`, `SYS003`,
`DMC400`). A session that greps first spends zero effort on it; a session
that doesn't will burn a live session re-deriving a 2026-06-12 result.

**Where good ideas historically came from** (worth actively watching):
- *Capture curiosities* — an odd payload noticed while mining for something
  else (the `"--"` placeholder in `userdata_str.config`).
- *App-behaviour mismatches* — the app does something the schema says it
  shouldn't, or vice versa (the app special-cases `voltage`; it never calls
  `get_model` for `ac_input`/`ac_output`/`battery_input` at all — §7.7).
- *HA user symptoms* — entities appearing wrong in Home Assistant (TPMS
  pressure as a Number entity → the whole ops-enum saga).

---

## Provenance and maintenance

- Authored 2026-07-12 for the ha-renogy-gateway skill library. Every
  historical claim above was verified against the repos on that date:
  sibling commits `626c809`, `84856f2`, `f282e53`, `ffac2f3`, `4d4b418`;
  HA commits `4108f95` (0.2.3), `831cd77` (0.2.4), `b1d260e` (0.2.7),
  `a6b0e7f` (0.2.9), `ae59831`, `d11f43e`, `46e3cb4`; PROTOCOL.md §2, §2.1,
  §7.4, §7.5, §7.7.
- The sibling repo's `docs/PROTOCOL.md` is canonical; the HA repo bundles a
  copy (`52496d7`). If section numbers referenced here drift, trust the
  sibling doc and update this skill.
- When a new saga completes (hypothesis → evidence → dated label), consider
  whether it makes a stronger worked example than one above — recipes should
  showcase the best real proof the project has.
- Sibling skills: `renogy-debugging-playbook` (routine faults),
  `renogy-failure-archaeology` (settled-findings catalogue),
  `renogy-curation-parity-campaign` (drift reconciliation),
  `renogy-protocol-reference` (the facts themselves),
  `renogy-change-control` (landing the resulting change).
