# identity-generator

A command-line tool that produces complete, self-consistent synthetic identities.
Every field in a generated profile (name, address, phone, postcode) belongs to
the same country and language, so the data reads as coherent rather than a random
mix of regional formats. Profiles are saved to a local history file and can be
exported as JSON or copied to the clipboard.

All data is entirely fictional. No real person is referenced or affected.

## Use cases

Registering on services that require personal data when you do not want to
share your real information, testing forms and sign-up flows during development,
and generating realistic seed data for demos.

## Requirements

Python 3.10 or newer. Install dependencies with:

    pip install -r requirements.txt

## Usage

Generate one identity with a random locale:

    python -X utf8 main.py

Generate with a specific locale:

    python -X utf8 main.py --locale es_ES

Export to a JSON file:

    python -X utf8 main.py --locale en_US --json

Copy the profile to the clipboard:

    python -X utf8 main.py --clipboard

Combine flags:

    python -X utf8 main.py --locale fr_FR --json --clipboard

Show history of all generated identities:

    python -X utf8 main.py --history

Show only the last five entries:

    python -X utf8 main.py --history --limit 5

List every supported locale:

    python -X utf8 main.py --list-locales

The -X utf8 flag is required on Windows to ensure special characters render
correctly in the terminal. On Linux and macOS it is optional.

## Supported locales (selection)

    es_ES   Spain
    es_MX   Mexico
    es_AR   Argentina
    es_CL   Chile
    es_CO   Colombia
    en_US   United States
    en_GB   United Kingdom
    fr_FR   France
    de_DE   Germany
    it_IT   Italy
    pt_BR   Brazil

Run --list-locales to see the full list.

## Generated fields

    full_name       First and last name matching the locale language.
    date_of_birth   Random date producing an age between 18 and 60.
    age             Calculated from date_of_birth.
    gender          Randomly male or female.
    address         Street address in the locale format.
    city            City consistent with the locale.
    postcode        Postcode in the locale format.
    country         Derived from the locale code.
    phone           Phone number in the locale format.
    occupation      Random job title.
    email           Temporary address from the 1secmail API, or a fallback
                    address using a known disposable domain when offline.
    username        ASCII-safe string built from the first name and birth year.
    nickname        Short informal handle derived from the first syllable
                    of the first name plus a random suffix.
    password        Cryptographically random string via secrets.token_urlsafe.
    id              UUID v4.
    created_at      ISO 8601 timestamp in UTC.

## History

Each generated identity is automatically appended to history.json in the
project directory. The file is created on first use and ignored by git so
it stays local. There is no automatic limit on the number of entries.

## Docker

Build the image:

    docker build -t identity-generator .

Generate one identity:

    docker run --rm identity-generator --locale en_US

Export to a JSON file and retrieve it on the host:

    docker run --rm -v "%cd%\output:/app/output" identity-generator --locale es_MX --json

On Linux or macOS replace %cd% with $(pwd).

The --clipboard flag does not work inside a container because there is no
display or clipboard mechanism available. Use --json and mount a volume instead.

## Source files

main.py

    Parses command-line arguments using argparse and coordinates all other
    modules. Handles terminal colour output via colorama so that escape codes
    work on Windows as well as Unix systems. The stdout encoding is set to
    UTF-8 at startup so that accented characters print correctly regardless
    of the system default.

generator.py

    Contains the generate_identity function, which creates a Faker instance
    for the chosen locale and uses it to produce every regional field. Helper
    functions handle gendered first names, ASCII-safe username construction,
    syllable-based nickname derivation, and safe calls to Faker providers that
    may not exist for every locale. The password field is produced by
    secrets.token_urlsafe, which uses the operating system cryptographically
    secure random source.

email_api.py

    Requests a real temporary inbox from the 1secmail public API. If the
    request fails for any reason (no internet access, timeout, unexpected
    response), it falls back to constructing a plausible address using a
    hardcoded list of known disposable mail domains. No API key is required.

history.py

    Reads and writes history.json. Every generated identity is appended to
    the list on disk. The get_all function accepts an optional limit to
    return only the most recent entries. If the file is missing or cannot
    be parsed, all read operations return an empty list and the next write
    recreates the file cleanly.

exporter.py

    Provides two output functions. to_json_file writes the identity dict to
    a file named after the username. to_clipboard formats the profile as a
    fixed-width plain-text block and copies it to the system clipboard using
    pyperclip. The plain-text format is intentionally simple so it can be
    pasted into any field without formatting artefacts.

## Possible extensions

The following ideas are starting points for anyone who wants to adapt the
tool to their own needs.

Add an avatar URL by calling a service such as DiceBear or UI Avatars with
the generated username as the seed. The URL can be stored in the identity
dict alongside the other fields.

Add a web API mode using Flask or FastAPI so that identities can be
requested over HTTP. This is useful when integrating the generator into
automated testing pipelines or browser automation scripts.

Add CSV export so that multiple identities can be generated in a batch and
opened directly in a spreadsheet.

Add a search command that filters history.json by country, date range, or
name substring, which becomes useful once the history grows large.

Add a profile picture generation step that calls a text-to-avatar API and
saves the image alongside the JSON export.

Add a delete command to remove a specific identity from history by its UUID,
for cases where a generated profile should no longer be stored locally.

Add support for custom locale weights so that, for example, Spanish locales
are picked more often than others when no --locale flag is provided.

Replace the plain-text clipboard format with a structured template that the
user can edit, allowing fields to be reordered or excluded to match a
particular registration form layout.

## Responsible use

This tool generates data that is completely fictional. It is intended for
privacy protection during online registrations and for software testing
purposes. Using it to impersonate real individuals, commit fraud, bypass
legal identity requirements, or engage in any illegal activity is outside
the intended scope and is the sole responsibility of the user. The authors
provide no warranty and accept no liability for any use of this software.

## License

MIT. See LICENSE for the full text.
