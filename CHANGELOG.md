# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to semantic versioning.

The version lives in `pyproject.toml`. This project does not use git tags, so a release is the state of `main` at the moment of publication plus the version number declared there.

## [1.0.0] - 2026-10-10

The first versioned release. Everything below landed on `main` between the initial commit and this one.

### Added

- Coherent synthetic identities where the locale drives every field at once, across 29 locales.
- Official national documents for ten locales (NIF/DNI, CURP, RUT, NUIP, SSN, NIN, NIR, RVNR, codice fiscale, CPF), each passing the country's own check digit, and null where no provider exists.
- Plausible passport serials per locale, following each country's official letter and digit shape.
- Real address datasets for eleven locales, built from GeoNames and OpenStreetMap, with real cities, real postcodes and real streets.
- Temporary inboxes from tempmail.lol and mail.tm, with a custom catch-all domain taking priority, and an offline mode that touches no network.
- A catch-all domain setup through `domains.json`, so addresses are deliverable to the user's real inbox.
- Provider API keys through `--set-key`, `--email-keys` and `--clear-key`, stored with restricted permissions and never printed in full.
- `--seed` for reproducible runs: the same seed repeats the whole profile, including the password and a whole batch, while ids stay unique.
- `--schema` publishing a JSON Schema 2020-12 of the identity object, which JSON, JSONL and CSV all validate against.
- `--jsonl` for newline-delimited JSON that a pipeline can read while the batch is still running.
- `--list-locales` showing a capability table per locale, including its document, passport shape, address convention and dataset sizes.
- `--verbose` writing structured detail to a log file and stderr.
- A network-marked suite of two tests that exercises the real tempmail.lol and mail.tm contracts, excluded from the default pytest run because it consumes rate limited quota, with every number in the README testing section pinned to the actual pytest collection by a guard.
- An `ATTRIBUTION.md` next to the address datasets, crediting GeoNames and OpenStreetMap inside the wheel itself.

### Changed

- The code moved into the `identity_generator` package, with `main.py` kept at the root as a thin launcher so `python -X utf8 main.py` is unchanged, and an `identity-generator` command once installed.
- The project packages itself through `pyproject.toml` built by hatchling, with the `identity-generator` console script as an entry point and the address datasets travelling inside the wheel.
- Every pull request builds the sdist and the wheel, runs `twine check`, and installs the wheel into a clean venv, where it must generate a real address from the packaged dataset before the change is accepted.
- Publication to PyPI is manual through a `workflow_dispatch` workflow on the `pypi` environment, which builds the package, refuses to republish an existing version, and ships with trusted publishing OIDC instead of a stored token.
- State, secrets and the log moved to a per-user data directory, overridable with `IDENTITY_HOME`, with a one-time migration from the old location.
- Exports now land in the current working directory instead of next to the code.
- The tempmail.lol free-tier rate limit moved from 25 per 5 minutes to 15 per 30 minutes, matching the change the provider made on 7 September 2026.

### Fixed

- Concurrent runs can no longer lose history entries, because the lock is exclusive at the filesystem level rather than in-process.
- A corrupted history or usage file is now backed up and reported instead of being silently reset.
- An interrupted write can no longer leave truncated JSON, since saves are atomic.
- The RUT validation now accepts every serial shape the provider can emit, including the short ones, which the previous regex rejected.
- Reading `pyproject.toml` in the test suite falls back to `tomli` on Python 3.10, where the standard library `tomllib` does not exist yet.

### Security

- Passwords carry roughly 90 bits of entropy worst case, above the NIST 800-63B recommendation, with no ambiguous glyphs.
- API keys are written atomically with owner-only permissions where the platform allows it, and are only ever displayed masked.