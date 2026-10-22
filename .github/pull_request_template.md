## Summary

- What changed and why?

## Type of change

- [ ] Bug fix (non-breaking change that fixes an issue)
- [ ] New feature (non-breaking change that adds functionality)
- [ ] Breaking change (fix or feature that changes existing behaviour)
- [ ] Documentation only
- [ ] Dependency update

## Linked issue

- Closes #

## Logs (redacted)

- Include relevant Home Assistant logs showing the behaviour before/after this change.
- Remove sensitive values (API keys, entity names you do not want to share).

## End-to-end test

- Describe the full flow tested in Home Assistant (config flow, voice query, service call...).
- Include exact steps and the observed result.

## Checklist

- [ ] `ruff check .` and `ruff format --check .` pass
- [ ] `pytest` passes, with new tests added for new behaviour
- [ ] `hassfest` and HACS validation pass in CI (they validate `manifest.json`, `strings.json` and translations)
- [ ] `CHANGELOG.md` updated (if user-facing)
- [ ] Translations updated (`strings.json`, `translations/en.json`, `translations/fr.json`) if the config flow or services changed
- [ ] I have read [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md)
