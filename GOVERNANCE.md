# Governance

## Maintainer

The project founder and current maintainer is **戴亿 (Dai Yi / DaiYiqq)**.

The maintainer is responsible for:

- release approval and version tags;
- security-sensitive changes;
- final review of changes that touch writes, snapshots, firewall rules,
  timezone changes or the local control API;
- keeping the public safety boundary accurate.

## Community roles

- **Contributors** submit code, documentation, tests, translations or issue
  reports.
- **Translators** maintain the English and Japanese READMEs and may review
  translation pull requests.
- **Reviewers** are contributors with a sustained record of useful reviews; the
  maintainer may ask them to review scoped pull requests.
- **Security reporters** use private GitHub Security Advisories rather than
  public issues.

## How decisions are made

- Small fixes and documentation changes: normal pull request review.
- User-facing behavior, data format, snapshot semantics, license or governance
  changes: public Discussion followed by a pull request and maintainer review.
- Security-sensitive write paths: maintainer review is required.
- Releases use version tags and release notes. The maintainer cuts releases
  after tests and a portable build pass.

## What the community will not accept

- server-side risk-control bypasses;
- credential, cookie, token or session-file collection;
- hidden telemetry;
- changes that write settings before creating a snapshot;
- claims that the project guarantees account outcomes;
- public disclosure of another person's private data or credentials.

## Licensing of contributions

Unless explicitly stated otherwise, contributions are licensed under
**AGPL-3.0-only**. See [LICENSING.md](LICENSING.md).

## Contact

Use GitHub Discussions for public coordination, Issues for reproducible bugs and
Security Advisories for vulnerabilities. The developer's public contact details
are in [AUTHORS.md](AUTHORS.md) and the README.
