# Security Policy

## Supported version

The supported version is the one published on PyPI, which is the state of `main` at the moment of publication. There are no LTS branches: fix releases come out of `main` and are published with a bumped version through the same workflow.

## How to report

Report vulnerabilities through GitHub private vulnerability reporting, in the Security tab of the repository. Please do not open a public issue for something that has not been reviewed as a vulnerability, because this tool is designed for privacy-sensitive work and an unfixed publication is itself an exposure.

If you prefer email, write to the address in the GitHub profile of the repository owner, and say in the first line that you are reporting a found vulnerability.

## What matters here

The project handles a few genuinely sensitive surfaces, so these are the kinds of report that receive immediate attention:

- Anything that leaks the stored API keys in `email_keys.json` or makes the tool print them fully. They are written with owner-only permissions and only displayed masked, and both claims are guarded by tests.
- Anything that crosses identity state between users differently from what the per-user directory promises, for example a write to a world-readable path or a state file that contains another user's data.
- A way for the tool to send personal data that comes from the user's real identity, rather than from the generated one, to a third party without an explicit action by the user, since isolating the real identity is the whole point of the tool.
- A dependency with a known vulnerability reachable from the network path, which the temporary inboxes use.

## What does not matter

The tool generates plausible but fictitious identities, the identity values it produces are not meant to be credentials for anything, and history.json is a local file the user controls, so please do not report "an identity is fake" or "seeded profiles repeat with the same seed" as vulnerabilities. They are features.

## What to expect

You get an acknowledgement within two working days and a plain-language explanation once it is analyzed. Fixes are released through the normal flow, with a version bump and a changelog entry naming the issue without the reporter's details unless they explicitly want credit.
