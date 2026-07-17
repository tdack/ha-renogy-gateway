---
name: renogy-build-and-env
description: >
  Recreate the ha-renogy-gateway development environment from scratch and
  diagnose environment-shaped failures. Load this skill when: setting up a
  fresh dev environment or venv for this repo; tests will not collect or will
  not run; pytest reports import errors, SyntaxError, or "no tests ran";
  ModuleNotFoundError for custom_components or homeassistant; local results
  disagree with CI (CI mismatch); choosing a Python version; installing the
  integration into a live Home Assistant for manual testing; or questions
  about pyproject.toml pytest settings, requirements_test.txt, or the
  Test/Validate GitHub workflows.
---

# Renogy Gateway: build and environment runbook

Repo: `ha-renogy-gateway` — a pure-Python Home Assistant HACS custom
integration (`custom_components/renogy_gateway`, `manifest.json` version
0.5.1 as of 2026-07-12). There is **no build step**: nothing to compile,
no packaging, no node/npm in this repo. "Building" here means creating a
venv that can run the pytest suite, and optionally installing the component
into a live Home Assistant.

The sibling repo `renogy-gateway` (Node/TypeScript, Node >= 24, npm
workspaces) is a separate project with its own environment; it is only
relevant as the canonical protocol reference. Nothing in this skill applies
to it.

## When NOT to use this skill

- Test-writing strategy, coverage, what to assert, fixture design →
  `renogy-validation-and-qa`.
- Releases, tagging, changelog, CI operations and day-to-day running →
  `renogy-run-and-operate`.

## 1. Requirements: Python 3.13, exactly

CI pins Python **3.13** (`.github/workflows/test.yml`,
`python-version: "3.13"`). Use 3.13 locally. This is not a soft preference:

- Commit `f3580cf` ("Fix Python 3.13-incompatible except clauses; pin CI to
  3.13", 2026-06-25) exists because the code once used unparenthesised
  `except A, B:` clauses, which only parse under PEP 758 (Python 3.14+).
  Home Assistant's stable runtime is 3.13, so real installs got a
  SyntaxError that CI missed while it was pinned to 3.14. The commit fixed
  the clauses in `custom_components/renogy_gateway/api/auth.py`,
  `api/discovery.py`, `coordinator.py`, `number.py` and pinned CI to 3.13.
  Moral: match CI's interpreter or you validate nothing.
- **Older** interpreters (3.12 and below) will typically fail before your
  code even matters: current `homeassistant` releases (pulled in by
  `pytest-homeassistant-custom-component`) declare a minimum Python and
  refuse to install or import on older interpreters, and the codebase
  follows current HA-core idioms.
- **Newer** interpreters (3.14+) may work but are exactly the trap
  `f3580cf` closed — a green run on 3.14 does not prove HA 3.13
  compatibility.

## 2. Environment from scratch

From the repo root (all paths repo-relative):

```sh
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements_test.txt
pytest
```

(Unverified by execution — see Provenance — but this is exactly what CI
runs: checkout, setup-python 3.13, `pip install -r requirements_test.txt`,
`pytest`.)

`requirements_test.txt` contains exactly two lines, both **unpinned**:

```
pytest-homeassistant-custom-component
pytest-asyncio
```

### What pytest-homeassistant-custom-component provides

It is a full Home Assistant test harness extracted from ha-core's own test
infrastructure. Installing it pulls in `homeassistant` itself plus pytest
plumbing, and provides:

- The `hass` fixture (a running in-memory HA instance per test).
- `pytest_homeassistant_custom_component.common` helpers —
  `tests/conftest.py` imports `MockConfigEntry` from there.
- The `enable_custom_integrations` fixture, which makes HA willing to load
  integrations from a local `custom_components/` directory instead of only
  built-ins.

### Why the integration is importable in tests

Two mechanisms, both required:

1. `pyproject.toml` sets `pythonpath = ["."]`, so `pytest` puts the repo
   root on `sys.path` and `import custom_components.renogy_gateway...`
   resolves.
2. `tests/conftest.py` defines an autouse fixture that switches on the
   harness's custom-integration loading for every test. Quoted verbatim:

   ```python
   @pytest.fixture(autouse=True)
   def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
       """Allow Home Assistant to load this custom integration during tests."""
   ```

   It does nothing itself; depending on `enable_custom_integrations`
   (provided by pytest-homeassistant-custom-component) is the whole trick.

`tests/conftest.py` also carries the shared mock world: `MOCK_TOKENS`,
`FieldSpec` fixtures (sensor/switch/light/number/select/binary-sensor/enum
cases, including unit-scaling regressions like mA→A and the Chinese "安培"
unit), five `RenogyDevice` mocks, two `SceneInfo` mocks, `mock_coordinator`,
`mock_setup_entry`, and `mock_config_entry`.

## 3. pyproject.toml, decoded

The entire file is four lines:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]          # bare `pytest` collects only tests/; ignores stray test-like files elsewhere
asyncio_mode = "auto"          # pytest-asyncio runs every `async def test_*` natively — no @pytest.mark.asyncio needed anywhere
pythonpath = ["."]             # repo root on sys.path so `custom_components.renogy_gateway` imports (pytest>=7 pythonpath feature)
```

There is nothing else in it — no `[project]`, no build-system, no tool
configs. Consequences:

- If `asyncio_mode` stopped applying (e.g. running pytest with a different
  rootdir so pyproject.toml is not found), async tests are collected but
  skipped/error with "async def functions are not natively supported".
- If `pythonpath` stopped applying, every test fails at import with
  `ModuleNotFoundError: No module named 'custom_components'`.

Both settings are discovered from the **rootdir**, so always run `pytest`
from the repo root. Running from inside `tests/` or elsewhere can pick a
different rootdir and silently drop all three settings — that is the
classic "worked yesterday" collection failure here.

## 4. Running the suite and subsets

```sh
pytest                                  # full suite
pytest tests/test_discovery.py          # one file
pytest tests/test_switch.py -k "turn_on"  # name filter
pytest -x                               # stop at first failure
pytest -x -k "config_flow" -vv          # combine as needed
```

Expected suite shape — **14 test files** in `tests/` (verified 2026-07-12;
if another skill or note claims 16, trust this list):

| File | Scope (from its docstring) |
|---|---|
| `tests/test_binary_sensor.py` | Binary sensor platform |
| `tests/test_config_flow.py` | Config flow |
| `tests/test_coordinator.py` | Coordinator |
| `tests/test_diagnostics.py` | Diagnostics |
| `tests/test_discovery.py` | Discovery module |
| `tests/test_init.py` | Integration setup (`__init__.py`) |
| `tests/test_light.py` | Light platform |
| `tests/test_models.py` | `FieldSpec.display_name` label resolution order |
| `tests/test_number.py` | Number platform |
| `tests/test_rtm.py` | RTM client unexpected-disconnect signalling |
| `tests/test_scenes.py` | Scene support (REST + RTM + button/switch) |
| `tests/test_select.py` | Select platform |
| `tests/test_sensor.py` | Sensor platform |
| `tests/test_switch.py` | Switch platform |

Note there is no `test_button.py` even though `button.py` exists — scene
buttons are covered in `tests/test_scenes.py`.

## 5. Lint and format: what is (not) configured

Verified 2026-07-12: the repo has **no** lint or format configuration. No
ruff/flake8/mypy/black/isort sections in `pyproject.toml`; no `.ruff.toml`,
`ruff.toml`, `setup.cfg`, `.flake8`, `mypy.ini`, `tox.ini`, or
`.pre-commit-config.yaml`. CI runs pytest, hassfest, and the HACS action —
no lint job.

Do not invent lint commands or claim "make lint" exists. That said, the
code was written against Home Assistant core conventions (typed fixtures,
platform-per-file layout, HA docstring style), so follow HA upstream style
de facto when editing — just know nothing enforces it here.

## 6. CI parity

To mirror CI exactly, reproduce `.github/workflows/test.yml` locally:

1. Python **3.13** interpreter (setup-python `"3.13"` = latest 3.13.x).
2. `pip install -r requirements_test.txt` — fresh, unpinned, so CI always
   gets the **latest** pytest-homeassistant-custom-component/HA.
3. `pytest` from the repo root, no extra flags.

It triggers on every push and pull request.

`.github/workflows/validate.yml` (push to main, PRs, weekly cron, manual)
runs two independent jobs you cannot fully reproduce with pip alone:

- **hassfest** (`home-assistant/actions/hassfest@master`) — HA's official
  integration validator: checks `manifest.json` correctness (domain, valid
  keys, `version` present for custom integrations, requirements format,
  codeowners), `strings.json`/translations consistency, services schema,
  etc.
- **HACS action** (`hacs/action@main`, `category: integration`) — checks
  HACS repository requirements: `hacs.json` present and valid (here:
  `{"name": "Renogy Gateway", "render_readme": true}`), repo structure
  (single integration under `custom_components/`), README, manifest fields
  HACS needs (documentation/issue_tracker URLs).

If Validate fails but Test passes, the problem is metadata
(`manifest.json`, `hacs.json`, strings/brands), not code.

## 7. Installing into a live Home Assistant

Two routes (from `README.md`):

**HACS custom repository** (normal route):
1. HACS → Integrations → ⋮ menu → **Custom repositories**.
2. URL `https://github.com/tdack/ha-renogy-gateway`, category
   **Integration**.
3. Install "Renogy Gateway" from HACS, then restart Home Assistant.

**Manual copy** (for testing local, uncommitted changes): copy the whole
`custom_components/renogy_gateway/` directory into the HA config dir's
`custom_components/`, then restart HA.

Then: **Settings → Devices & services → Add integration → "Renogy
Gateway"**. The config flow asks for the **Renogy account email and
password**; if the account has multiple gateways it asks which one to add.

**Safety rule (non-negotiable):** a live install talks to the user's real
rig over Renogy's cloud. Switch, light, number, select, and scene-button
entities switch **physical circuits**. Do not toggle, dim, run scenes, or
write any setting on a live install without explicit human permission for
that specific action. Reading sensors is fine.

## 8. Known traps

- **Wrong Python version.** 3.14+: passes locally where 3.13 (and real HA)
  would SyntaxError — the exact `f3580cf` failure mode; also risks pip
  resolving an HA version newer than users run. 3.12 and below: pip refuses
  to install `homeassistant`, or imports fail on new syntax/typing. First
  diagnostic for any weird env failure: `python --version` inside the venv.
- **Unpinned requirements drift.** `requirements_test.txt` pins nothing, so
  each fresh install tracks the latest pytest-homeassistant-custom-component,
  which tracks HA releases. A suite that passed last month can fail today
  with zero repo changes — suspect the harness before the code. To bisect,
  pin temporarily: `pip install "pytest-homeassistant-custom-component==<ver>"`
  (its version maps to an HA release; check its changelog). Do not commit
  the pin without a deliberate decision — CI's freshness is intentional, it
  is an early-warning canary for upcoming HA releases.
- **Running pytest from the wrong directory.** Subdirectory runs can change
  pytest's rootdir, dropping `pythonpath`/`asyncio_mode`/`testpaths`.
  Symptoms: `ModuleNotFoundError: No module named 'custom_components'`, or
  async tests erroring as unsupported. Fix: run from the repo root.
- **asyncio_mode assumptions.** Tests carry no `@pytest.mark.asyncio`
  markers because `asyncio_mode = "auto"` supplies them. Copying a test
  into another project (or a scratch runner) without that setting makes
  every async test fail. Conversely, do not add the markers here.
- **`homeassistant` in the venv is a test dependency, not the app.** Do not
  try to `hass -c` from this venv expecting a configured instance; live
  testing goes through a real HA install (section 7).

## Provenance and maintenance

- Authored 2026-07-12 against repo state at that date (integration version
  0.5.1). Ground truth read directly from: `pyproject.toml`,
  `requirements_test.txt`, `.github/workflows/test.yml`,
  `.github/workflows/validate.yml`, `tests/conftest.py`, `tests/` listing
  and docstrings, `hacs.json`, `custom_components/renogy_gateway/manifest.json`,
  `README.md`, and `git show f3580cf`.
- **Honesty note:** the authoring environment had only Python 3.10, so the
  venv/pytest command sequence in section 2 was **not executed** here. It
  is transcribed from the CI workflow (which is green in practice) and
  standard venv usage, not verified in anger in this session. Everything
  quoted from files (fixture code, workflow steps, file lists, commit
  message) was read verbatim.
- Volatile facts to re-check when maintaining: CI Python version, the
  14-file test list, absence of lint config, requirements_test.txt contents,
  README install steps, manifest version.
