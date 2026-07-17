# Project instructions

## Skills

This repo ships a library of Claude Code skills under `.claude/skills/`. Each
skill's frontmatter `description` spells out its own trigger conditions in
detail — treat those as authoritative. Load the matching skill proactively,
before starting the matching work, not only when the user asks for it by
name.

Two skills gate almost everything else and should be loaded first when they
apply:

- `renogy-change-control` — before making **any** change to this repo. It
  decides whether the change needs a release, what evidence bar it must
  clear, and whether it belongs here or in the sibling `renogy-gateway` repo
  instead.
- `renogy-architecture-contract` — before **any structural change** (new
  platform/entity type, edits to the coordinator or the `api/` layer
  boundary, discovery/reconnect/token/write paths, support for a new device
  model) — and especially whenever you're tempted to hardcode device-specific
  knowledge (SKU tables, channel lists, allowlists).

Also check `renogy-failure-archaeology` before re-investigating a bug or
protocol question that feels familiar — it catalogues settled findings and
dead ends so you don't re-fight an old battle.

| Skill | Use for |
|---|---|
| `renogy-change-control` | Approval policy: is this change/release allowed to ship, and where does it belong |
| `renogy-architecture-contract` | Invariants to respect before any structural change |
| `renogy-protocol-reference` | Wire-level facts about the gateway API/RTM protocol (auth, ops, schema, writes, scenes) |
| `renogy-analysis-and-evidence` | Proving a new protocol/schema fact: evidence bar, HAR mining, live probing |
| `renogy-failure-archaeology` | Checking whether an investigation has already been fought, and how it ended |
| `renogy-curation-and-flags` | Adding/changing curation constants; a field surfacing as the wrong entity type |
| `renogy-curation-parity-campaign` | Reconciling curation drift against the canonical sibling TypeScript repo |
| `renogy-debugging-playbook` | Symptom-to-cause triage for a broken or misbehaving integration |
| `renogy-diagnostics-and-tooling` | Reading diagnostics dumps/logs, mining HARs, release-consistency checks |
| `renogy-validation-and-qa` | What evidence a fix needs before it's "done"; adding or locating tests |
| `renogy-build-and-env` | Setting up or fixing the dev environment; CI-vs-local mismatches |
| `renogy-run-and-operate` | Step-by-step release process, HACS publishing, live-install operation |
| `renogy-docs-and-writing` | House style for PROTOCOL.md, CHANGELOG.md, README.md, CLAUDE.md, commit messages |
| `renogy-research-frontier` | Roadmap prioritisation — what to work on next |

## Releases

Before bumping the version in `custom_components/renogy_gateway/manifest.json`
and tagging a release, update [CHANGELOG.md](CHANGELOG.md) with an entry for
the new version, summarizing the notable changes since the previous tag.
Commit the changelog update along with (or just before) the version bump
commit. Do not tag a release without a corresponding changelog entry.
