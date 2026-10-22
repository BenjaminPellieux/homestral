# Contributing to HomeStral

Thanks for helping! This page covers the development setup, the checks that run in CI and how releases are cut.

By participating in this project you agree to abide by our [Code of Conduct](../CODE_OF_CONDUCT.md). If you find a security vulnerability while developing, do not open a public issue — see [SECURITY.md](../SECURITY.md) for private reporting.

## Development setup

Home Assistant 2026.2.3+ requires Python 3.13.

```bash
git clone https://github.com/BenjaminPellieux/homestral.git
cd homestral

# With uv (recommended)
uv venv --python 3.13 .venv
source .venv/bin/activate
PYTHON=python scripts/setup

# Or with a plain venv
python3.13 -m venv .venv
source .venv/bin/activate
scripts/setup
```

`scripts/setup` installs `requirements.txt` (Home Assistant, the Mistral SDK, pytest, ruff) plus the exact `hassil` / `home-assistant-intents` versions pinned by the installed Home Assistant release.

## Running the checks

```bash
ruff check .            # lint
ruff format --check .   # formatting (run `ruff format .` to fix)
pytest -q               # unit tests
```

All three run in GitHub Actions on every push and pull request, together with the [HACS action](https://github.com/hacs/action), [hassfest](https://github.com/home-assistant/actions#hassfest), [CodeQL](.github/workflows/codeql.yaml) (Python SAST, also on a weekly schedule) and [OpenSSF Scorecard](.github/workflows/scorecard.yaml). The test workflow runs twice: once against the minimum Home Assistant version declared in `hacs.json` (2026.2.3) and once against the latest release.

## Testing in a real Home Assistant

1. Copy (or symlink) `custom_components/homestral` into `<config>/custom_components/` of a development instance.
2. Restart Home Assistant and add the integration from **Settings → Devices & services**.
3. Enable debug logging to follow the STT, conversation and tool-loop steps:

   ```yaml
   logger:
     logs:
       custom_components.homestral: debug
   ```

## Pull requests

- Create a branch from `main`.
- Keep the change focused; add or update tests next to the code you touch.
- Update `strings.json` and `translations/{en,fr}.json` together whenever the config flow, options or services change.
- Add a line to `CHANGELOG.md` under `[Unreleased]` for user-facing changes.
- Fill in the pull request template (redacted logs and the end-to-end flow you tested in Home Assistant).
- Wait for all status checks to pass: `ruff`, `pytest` (minimum and latest Home Assistant), hassfest, HACS validation, CodeQL and OpenSSF Scorecard. Sensitive paths (integration code, workflows, `SECURITY.md`, `manifest.json`) also require the maintainer's review via `CODEOWNERS`.

## Releasing

1. Bump `version` in `custom_components/homestral/manifest.json`.
2. Move the `Unreleased` items in `CHANGELOG.md` under the new version with today's date.
3. Merge to `main`, then tag and push:

   ```bash
   git tag X.Y.Z
   git push origin X.Y.Z
   ```

The `Release` workflow checks that the tag matches the manifest version and publishes a GitHub release with generated notes. HACS picks the new version up from that release.
