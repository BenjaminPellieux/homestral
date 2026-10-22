# Security Policy

## Supported Versions

Only the latest release of HomeStral receives security fixes.

| Version | Supported |
| --- | --- |
| Latest release (see [Releases](https://github.com/BenjaminPellieux/homestral/releases)) | Yes |
| Older releases | No |

We recommend always running the latest version, installed through HACS or the
latest GitHub release.

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

Instead, use GitHub's **private vulnerability reporting**:

1. Go to the [Security Advisories](https://github.com/BenjaminPellieux/homestral/security/advisories) page.
2. Click **Report a vulnerability**.
3. Fill in the details and submit.

Alternatively, email **benjaminpellieux5@gmail.com** with the subject line
`[SECURITY] HomeStral — <short description>`.

### What to include

- A description of the vulnerability and its potential impact.
- Steps to reproduce (proof of concept, logs, screenshots).
- Affected versions and environment (Home Assistant version, install method).
- Any suggested fix or mitigation, if you have one.

**Never include real Mistral API keys or personal data in your report.**
Redact logs before sharing.

### What to expect

| Stage | Timeline |
| --- | --- |
| Acknowledgement of your report | Within 48 hours |
| Initial assessment (severity, validity) | Within 7 days |
| Fix or mitigation for confirmed issues | Depends on severity — critical issues are prioritised |
| Public disclosure (coordinated) | After a fix is released, or 90 days after the report, whichever comes first |

We follow **coordinated disclosure**: we will work with you to fix the issue
before any public announcement. We will credit you in the release notes unless
you prefer to remain anonymous.

## Security Best Practices for Users

HomeStral handles your **Mistral API key** and can **control your Home Assistant
devices**. Follow these practices to stay safe:

- **Never share your Mistral API key.** It is stored in Home Assistant's config
  entry and is never logged by the integration (verify with debug logs if in doubt).
- **Use a dedicated API key** for HomeStral with spending limits set in the
  [Mistral console](https://console.mistral.ai). Revoke it immediately if you
  suspect a leak.
- **Keep Home Assistant and HomeStral up to date.** Security fixes ship in new
  releases.
- **Review tool-call logs.** Enable debug logging (`custom_components.homestral:
  debug`) to audit which devices the AI controls:
  ```yaml
  logger:
    logs:
      custom_components.homestral: debug
  ```
- **Restrict network access** if possible — HomeStral only needs outbound HTTPS
  to `api.mistral.ai`.
- **Do not expose Home Assistant to the internet** without additional
  protections (reverse proxy, VPN, 2FA).

## Scope

The following are **in scope** for security reports:

- The HomeStral integration code (`custom_components/homestral/`).
- API key handling, logging, and storage.
- Device control logic and privilege escalation within Home Assistant.
- CI/CD workflows and GitHub Actions in this repository.
- Dependencies declared in `manifest.json` and `requirements.txt`.

The following are **out of scope**:

- Vulnerabilities in Home Assistant core (report to [Home Assistant](https://www.home-assistant.io/security/)).
- Vulnerabilities in the Mistral AI API or models (report to [Mistral AI](https://mistral.ai/contact)).
- Social engineering or phishing attacks.
- Issues requiring physical access to the Home Assistant host.

## Security Measures in Place

- **API key validation** at setup time against the Mistral API.
- **API key never logged** in plaintext (verified by tests in `tests/test_sensor.py`).
- **Blocking calls run in an executor** — no event-loop blocking, no key exposure in tracebacks.
- **Minimal GitHub Actions permissions** — workflows declare `contents: read`; `security-events: write` only in CodeQL and Scorecard, `id-token: write` only in Scorecard, and `contents: write` only in the release workflow.
- **Actions pinned to commit SHAs** — no mutable `@vX` tags on third-party actions (CodeQL and Scorecard actions are the documented, reviewed exception while their pinning is finalised).
- **CodeQL** — Python SAST (`security-extended` queries) on every push/PR and weekly.
- **OpenSSF Scorecard** — continuous supply-chain security score, results published to Security Advisories.
- **Dependabot** — weekly dependency updates for pip and GitHub Actions, with PR limits and reviewer assignment.
- **Ruff linting** and **hassfest** validation in CI.
- **HACS validation** in CI.
- **Single config entry** — prevents duplicate-key confusion.

Thank you for helping keep HomeStral and its users safe.
