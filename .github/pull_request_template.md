## What changed

<!-- A summary of the change in product terms: what a user of the tool can do differently now, even if the answer is "nothing, this is refactor material". -->

## How it is covered

<!-- Name the tests that verify the change. If it touches a new code path, paste the pytest summary line of your local run. The suite also guards the repository itself, so say which drift guards now exist or grew. -->

## What it touches

<!-- Check what applies, so a reviewer knows which frozen surfaces moved. -->

- [ ] CLI flags (README and CHANGELOG moved together)
- [ ] The identity schema (tests/test_schema.py guards the schema-display pair)
- [ ] pyproject, requirements or dependencies (the drift guards must still pass)
- [ ] The address datasets (check ATTRIBUTION.md still matches reality)
- [ ] Documentation only

## Checklist

- [ ] `python -X utf8 -m pytest tests/ -q` is green on my machine
- [ ] New README claims live on one line per paragraph, with no bold and no semicolons
- [ ] CHANGELOG.md updated if the tool's behavior changed
- [ ] No git tag involved in the release flow
