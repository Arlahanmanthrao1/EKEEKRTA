# Contributing

EKEEKRTA is currently maintained as an academic portfolio project. Contributions should preserve its central guarantees: institution isolation, server-side authorization, explicit external-system boundaries and honest feature status.

## Before changing code

1. Read the [architecture](docs/architecture.md) and [feature status](docs/features.md).
2. Identify the affected institution type and roles.
3. Check whether the change alters stored data, permissions, provider credentials or privacy expectations.
4. Keep unrelated local changes intact.

## Development workflow

1. Create a focused branch.
2. Implement backend authorization before relying on frontend visibility.
3. Add or update tests for an allowed path and a denied path.
4. Update relevant Markdown when behavior, configuration or feature status changes.
5. Run the checks in [Local development](docs/local-development.md).
6. Inspect the staged diff for credentials, personal data, databases, recordings and generated artifacts.

## Code expectations

- Do not trust institution, role, marks or moderator authority supplied by the browser.
- Scope database reads and writes by the authenticated user's institution and resource access.
- Validate external responses and use explicit timeouts.
- Keep external-system failures recoverable; do not hide them behind fabricated success states.
- Never expose quiz answers, hidden test cases, tokens or private AI/recording data to unauthorized users.
- AI-assisted mutations must remain previewable, auditable and permission checked at execution.
- Do not add dummy production records to make dashboards appear active.

## Documentation expectations

Use the repository status language consistently:

- **Implemented** — code and a working flow exist.
- **Configurable** — code exists but credentials/infrastructure are required.
- **Foundation** — supporting workflow exists but the claimed model/intelligence is not bundled.
- **Planned** — not currently available.

Do not describe a mocked provider response, UI placeholder or navigation label as a completed feature.

## Commit hygiene

- Use an imperative, scoped commit message.
- Never commit `.env`, keys, database files, recordings, private datasets or institution exports.
- Avoid mixing generated deliverables with application changes unless the deliverable is the purpose of the commit.
- Explain schema and configuration changes in the commit or pull-request description.

## Reporting security issues

Do not include credentials, personal data or exploit details in a public issue. Follow the private-contact guidance in [Security and privacy](docs/security-and-privacy.md).
