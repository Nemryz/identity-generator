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

Generate a plausible email without a real inbox (no network calls):

    python -X utf8 main.py --email-offline

Reuse the most recent usable inbox instead of creating a new one:

    python -X utf8 main.py --reuse

Read the inbox of the latest identity (or of a specific UUID):

    python -X utf8 main.py --check-inbox
    python -X utf8 main.py --check-inbox <uuid>

Show email provider usage counters:

    python -X utf8 main.py --email-usage

Wait N seconds after generating (throttle for script loops):

    python -X utf8 main.py --delay 2

Generate 50 identities as CSV rows for database seeding:

    python -X utf8 main.py --count 50 --csv

Batch mode prints one compact line per identity, writes all of them to
history and writes identities.csv (overwritten every run, no email_token
column). Combine with --delay to stay inside email provider limits, or
--email-offline for a fully offline batch.

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
    address         Street address in the locale format. For the 11
                    locales with an address dataset (see Data sources)
                    it combines a real street name with a house number
                    following the local convention ("Calle X 123" in
                    Spain, "123 Main Street" in the US, "Rua X, 123" in
                    Brazil); other locales use Faker.
    city            For the 11 dataset locales, a real city from the
                    dataset picked weighted by population; other locales
                    use Faker.
    postcode        Real postal code of the generated city (dataset
                    locales) or a Faker postcode in the locale format.
    country         Derived from the locale code.
    phone           Phone number in the locale format.
    occupation      Random job title.
    email           Real temporary inbox with an address built from the
                    identity's names (tempmail.lol, then mail.tm), or a
                    plausible address on a disposable domain when offline.
    email_token     Inbox token enabling the --check-inbox command.
                    Null when the email has no real inbox.
    email_provider  Provider that owns the inbox ("tempmail", "mailtm" or
                    "offline"); tells --check-inbox which API to query.
    username        ASCII-safe string built from the first name and birth year.
    nickname        Short informal handle derived from the first syllable
                    of the first name plus a random suffix.
    password        Random 16-character password with guaranteed uppercase,
                    lowercase, digit and symbol, avoiding ambiguous
                    characters (I, l, 1, O, 0).
    id              UUID v4.
    created_at      ISO 8601 timestamp in UTC.

## Temporary email providers

Emails are created against two free public APIs (no account or API key
required), in order:

0. Custom catch-all domain (see below), when configured.
1. tempmail.lol: the inbox token is returned in the same response as the
   address. Free tier: inbox expires after 1 hour, 25 inboxes per 5 minutes
   per IP.
2. mail.tm: custom address, its /token endpoint can lag behind account
   creation, so the token is best-effort. 8 requests per second per IP.

When both providers are unreachable or rate-limited, a plausible address
on a known disposable domain is produced without an inbox (email_token is
null). Use --email-offline to force this mode.

Read operations (--check-inbox) query the inbox with the stored token:
tempmail.lol consumes the emails it returns (limit 10 by default), mail.tm
keeps them. Identities created before the email_provider field existed
cannot be read; regenerate them.

Usage counters per provider are persisted in email_usage.json (ignored by
git) so the chain skips a provider before it rejects the request. A warning
is printed to stderr at 80% of a provider's limit. Reads are counted too
(read_tempmail / read_mailtm, informational, no hard limit).

## Custom catch-all domain

Many services block disposable domains outright. If you own a domain you
can make every generated address deliverable with a catch-all rule — no
API, no rate limits, nothing to block. This is the recommended setup for
regular use.

1. In Cloudflare Email Routing (free) or ImprovMX, add your domain and a
   catch-all rule that forwards to your real inbox.
2. Copy `domains.example.json` to `domains.json` (ignored by git) and put
   your domain in it:

       {"domains": ["mail.midominio.com"]}

3. Done. Generated addresses look like
   `carlos.garcia.4821@mail.midominio.com` and arrive in your inbox.
   --check-inbox reports that the address is forwarded, since there is no
   API to read (the messages land in your real mail client).

Without domains.json the tool behaves exactly as before (tempmail.lol
then mail.tm, then offline fallback).

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
    syllable-based nickname derivation, safe calls to Faker providers that
    may not exist for every locale, and NIST-aligned password generation
    (16 characters, guaranteed character classes, no ambiguous glyphs)
    via the operating system secure random source.

email_api.py

    Creates a real temporary inbox whose address is built from the
    identity's names, using the tempmail.lol API first and the mail.tm API
    as fallback. When a custom catch-all domain is configured in
    domains.json it is used first: addresses are deliverable to the user's
    real inbox with no API and no rate limits. The returned token is
    stored with the identity so the inbox can be read later with
    check_inbox(), which fetches received emails for --check-inbox. When
    all real-inbox providers are unreachable or rate-limited, a plausible
    address is constructed locally using a hardcoded list of known
    disposable mail domains. Per-provider usage counters are persisted in
    email_usage.json to respect rate limits. No API key or account is
    required.

history.py

    Reads and writes history.json. Every generated identity is appended to
    the list on disk (batches via append_many, one locked write). The
    get_all function accepts an optional limit to return only the most
    recent entries. get_by_uuid finds an identity by its ID (used by
    --check-inbox), and find_usable_email returns the most recent inbox
    that can be reused (used by --reuse). If the file is missing or cannot
    be parsed, all read operations return an empty list. A corrupted file
    is backed up to history.corrupt.<timestamp>.bak and announced on
    stderr instead of being silently destroyed.

exporter.py

    Provides three output functions. to_json_file writes the identity dict
    to a file named after the username. to_csv_file writes every identity
    as a row in identities.csv (overwritten each run; email_token is
    excluded) for database seeding. to_clipboard formats the profile as a
    fixed-width plain-text block and copies it to the system clipboard
    using pyperclip. The plain-text format is intentionally simple so it
    can be pasted into any field without formatting artefacts.

## Data sources

The address datasets in data/addresses/ are generated by tools/build_datasets.py
from two open data sources, used so that every generated address contains a
real city, a real postal code and real street names:

- GeoNames (CC-BY 4.0, https://www.geonames.org/export/): the cities15000
  dataset (city names, population, coordinates) and the per-country postal
  code datasets.
- OpenStreetMap (c) OpenStreetMap contributors (ODbL,
  https://www.openstreetmap.org/copyright), queried through the public
  Overpass API.

Each locale file contains up to 300 cities sorted by population, their postal
codes (when the country dataset has one; coverage is 70-98%) and up to 250
street names. To regenerate them:

    py -3.13 -X utf8 tools/build_datasets.py

Overpass is rate-limited and occasionally drops queries, so the script caches
all downloads in the system temp directory and retries across several public
mirrors. Use --skip-osm to refresh only the GeoNames part reusing the streets
already on disk, and --sleep to tune the delay between queries.

Known limitations: the GeoNames Colombia postal file has no entry for Bogota,
and the Mexico file has no standalone "Ciudad de Mexico" entry, so those
cities keep a null postal code or a code from a matching region variant.
Street names are filtered by language (non-Latin scripts and foreign
first words are dropped), but the country grid cells overlap neighbouring
countries, so a few cross-border names may remain in the France, Germany,
Italy and Brazil datasets; the UK dataset may include some Irish names
(the two are not distinguishable by word lists). The datasets can be
refreshed or replaced with a country-polygon (area) Overpass query by
editing tools/build_datasets.py.

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
