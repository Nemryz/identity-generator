# Contributing

Thanks for looking at this. It is a small project, so the bar for a change is mostly "does it keep the suite honest and the docs true".

## Getting set up

```bash
git clone https://github.com/Nemryz/identity-generator.git
cd identity-generator
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

The editable install gives you the `identity-generator` command. Running `python -X utf8 main.py` from the root works too and is equivalent.

Python 3.10 or newer. Windows needs the `-X utf8` flag everywhere, otherwise accented characters in the terminal can break.

## Running the tests

```bash
python -m pytest tests/ -q
```

The whole suite runs offline in well under a minute: the only external interaction is the temporary email API and it is stubbed. A couple of things worth knowing:

- Tests never touch your real data. `tests/conftest.py` points every state, secret and config file at a throwaway directory, so a forgotten fixture cannot write into your history.
- A few tests assert things about the repository itself, not about the code. They check that every file compiles, that the declared dependencies match the imports, and that the README keeps describing the modules and the test counts that actually exist. If you add a module or a test file and the suite complains about the README, that is the guard doing its job.

## The git flow

Work on a branch, never straight on `main`:

```bash
git switch -c feat/mi-cambio
```

Commit in small logical units with `git add` on the specific paths rather than `git add .`, then open a pull request and let the CI run on it before merging:

```bash
git push -u origin feat/mi-cambio
gh pr create --base main --head feat/mi-cambio --title "..." --body "..."
gh pr checks --watch
gh pr merge --squash
```

The matrix runs on ubuntu and windows with Python 3.10 and 3.12, which is not decoration: a missing `encoding="utf-8"` in a subprocess helper once passed locally and failed only on windows. Squash-merge so `main` stays readable.

If a conflict shows up, `git fetch origin` then `git rebase origin/main`, resolve the marked blocks, `git add` and `git rebase --continue`. `git rebase --abort` throws it away and starts over.

## Adding a locale

The tables and the display labels have to move together, and there are guards that will tell you if they do not:

1. Add the locale to `LOCALE_COUNTRY_MAP` in `identity_generator/generator.py` if you want a readable country name.
2. If Faker has an official document for it, add the provider method to `_NATIONAL_ID_PROVIDERS` and a human name to `_NATIONAL_ID_LABELS`. Those two maps are separate on purpose, because several locales share the `ssn` provider while shipping three different documents.
3. Add the passport shape to `_PASSPORT_FORMATS` as a `(letters, digits)` pair.
4. If the locale has a real address dataset, drop the JSON under `identity_generator/data/addresses/`.
5. Describe the new field or locale in the README if the guards ask you to.

A test validates generated identities against the published JSON Schema, and another refuses a provider without a label, so a half-finished addition fails with a message naming the offender instead of rendering a blank cell in the table.

## Comments and docstrings

Keep them in first person and one line per block, the way the rest of the code does. Public functions keep a docstring because they are the documented surface, internal helpers with a short note get a `#` comment above them, and anything longer than a couple of sentences stays a docstring so it does not get lost.

No bold and no semicolons in the README, one paragraph per line, and no hard wrapping mid-sentence. There is a test for each of those.

## Bug reports

A good one includes the command you ran, the locale, the Python version, the operating system, and what you expected instead. If the output was wrong, the profile that produced it is the most useful thing you can attach, since `--verbose` keeps it in the log.

## Responsible use

This tool generates entirely fictional data for privacy protection during registrations and for software testing. Using it to impersonate real people, commit fraud or bypass legal identity requirements is out of scope, and see the section of the same name in the README.