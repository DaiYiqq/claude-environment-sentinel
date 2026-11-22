## Summary

Describe the problem and the change.

## Type of change

- [ ] Bug fix
- [ ] Documentation / translation
- [ ] Test
- [ ] Feature (no server-side bypass)
- [ ] Refactor

## Safety checklist

- [ ] No credentials, cookies, tokens, real IPs or snapshot contents are included.
- [ ] Write paths still create a snapshot before any setting is changed.
- [ ] Restore still deletes values that were originally absent.
- [ ] The local control API still requires token + explicit confirmation.
- [ ] No server-side risk-control bypass is introduced.
- [ ] Documentation keeps the no-guarantee boundary.

## Verification

- [ ] `python -m unittest discover -s tests`
- [ ] `node --check sentinel/webui/app.js`
- [ ] `node --check docs/assets/site.js`
- [ ] `python -m sentinel smoke-test`
- [ ] Dark and light themes checked (if UI changed)
- [ ] Mobile width checked (if site changed)

## Licensing

- [ ] I agree to license this contribution under AGPL-3.0-only.
