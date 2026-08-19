# identity-generator

A command-line tool that produces complete, self-consistent synthetic identities.
Every field in a generated profile (name, address, phone, postcode) belongs to
the same country and language, so the data reads as coherent rather than a random
mix of regional formats. Profiles are saved to a local history file and can be
exported as JSON or CSV, or copied to the clipboard.

All data is entirely fictional. No real person is referenced or affected.

## Use cases

Registering on services that require personal data when you do not want to
share your real information, testing forms and sign-up flows during development,
and generating realistic seed data for demos.

## Requirements

Python 3.10 or newer. Install dependencies with:

    pip install -r requirements.txt

To run the automated test suite (see Testing) also install the development
dependencies:

    pip install -r requirements-dev.txt

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
                    Brazil). Other locales use Faker.
    city            For the 11 dataset locales, a real city from the
                    dataset picked weighted by population. Other locales
                    use Faker.
    postcode        Real postal code of the generated city (dataset
                    locales) or a Faker postcode in the locale format.
    country         Derived from the locale code.
    national_id     Official national ID for locales with a Faker
                    provider: DNI/NIF (Spain), CURP (Mexico), RUT (Chile),
                    cédula NUIP (Colombia), SSN (US), National Insurance
                    Number (UK), NIR (France), German pension number
                    (Germany), codice fiscale (Italy), CPF (Brazil).
                    Null for locales without one (e.g. es_AR).
    passport_number Plausible passport serial in the locale's official
                    length/shape (e.g. 9 digits for the US, 3 letters +
                    6 digits for Spain). Always present.
    phone           Phone number in the locale format.
    occupation      Random job title.
    email           Real temporary inbox with an address built from the
                    identity's names (tempmail.lol, then mail.tm), or a
                    plausible address on a disposable domain when offline.
    email_token     Inbox token enabling the --check-inbox command.
                    Null when the email has no real inbox.
    email_provider  Provider that owns the inbox ("tempmail", "mailtm" or
                    "offline"). Tells --check-inbox which API to query.
    username        ASCII-safe string built from the first name and birth year.
    nickname        Short informal handle derived from the first syllable
                    of the first name plus a random suffix.
    password        Random 16-character password with guaranteed uppercase,
                    lowercase, digit and symbol, avoiding ambiguous
                    characters (I, l, 1, O, 0). The four guaranteed class
                    characters plus twelve drawn from the full 64-character
                    pool give roughly 90 bits of entropy worst case, well
                    above the NIST 800-63B recommendation.
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
cannot be read, so regenerate them.

Usage counters per provider are persisted in email_usage.json (ignored by
git) so the chain skips a provider before it rejects the request. A warning
is printed to stderr at 80% of a provider's limit. Reads are counted too
(read_tempmail / read_mailtm, informational, no hard limit).

All API calls use a 5-second timeout, so a provider that stops responding
(connection hangs rather than failing) still falls through to the next
step of the chain instead of blocking the CLI indefinitely. If
email_usage.json is ever corrupted it is backed up to
email_usage.corrupt.<timestamp>.bak and the counters restart from zero
with a logged warning, mirroring the history.json protection.

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

Writes take an exclusive lock file created with O_EXCL, which the
operating system guarantees atomically across processes, so two parallel
CLI runs cannot lose entries (verified by a two-process test). Saves are
atomic too (temporary file renamed into place), so an interrupted write
never leaves a truncated history. If the file is corrupted it is backed
up to history.corrupt.<timestamp>.bak and the error is logged instead of
being silently destroyed.

## Testing

The project ships a fully automated test suite written with pytest,
covering 243 test cases across 9 modules:

    tests/test_generator.py   43 tests   identity fields, names, passwords
    tests/test_datasets.py    66 tests   address dataset schema and quality
    tests/test_addresses.py   25 tests   real addresses and postcodes
    tests/test_documents.py   25 tests   official national IDs and passports
    tests/test_email_api.py   35 tests   email provider chain and fallbacks
    tests/test_history.py     15 tests   persistence, locking, concurrency
    tests/test_main.py        14 tests   command-line flags and output
    tests/test_exporter.py     5 tests   JSON, CSV and clipboard exports
    tests/test_properties.py  15 tests   property-based invariants (Hypothesis)

Run the whole suite with:

    python -X utf8 -m pytest tests/ -q

The tests are integration-first: they exercise the real filesystem, the
real Faker providers and the real address datasets in data/addresses/.
The only external interaction that is stubbed is the temporary-email API,
so the suite runs offline and never hits the network. Every feature is
covered by at least one test that follows its happy path end to end.

Property-based tests (test_properties.py, using Hypothesis) generate
random unicode names and sample exotic Faker locales to verify the
invariants that directed tests cannot enumerate by hand: every generated
identity has non-empty ASCII-safe usernames and emails, valid passport
shapes, and dataset addresses that always stay inside their locale's
data. A real two-process concurrency test verifies that parallel CLI
runs never lose history entries (see History).

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
    of the system default. Calls setup_logging() at startup; --verbose
    enables DEBUG detail in the log file and on stderr.

applog.py

    Minimal structured logging shared by every module. setup_logging()
    attaches a file handler (identity-generator.log, ignored by git,
    overridable via IDENTITY_LOG_FILE) and a stderr handler; modules log
    through get_logger() instead of printing to stderr directly. Outside
    main.py the loggers are safe to use with no configuration, so tests
    capture records via pytest's caplog.

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
    as a row in identities.csv (overwritten each run, with the email_token
    column excluded) for database seeding. to_clipboard formats the profile
    as a fixed-width plain-text block and copies it to the system clipboard
    using pyperclip. The plain-text format is intentionally simple so it
    can be pasted into any field without formatting artefacts.

tools/build_datasets.py

    One-time offline script that builds the address datasets in
    data/addresses/ from GeoNames and OpenStreetMap data (see Data
    sources). Caches downloads in the system temp directory, retries
    across Overpass mirrors, and learns the zip-admin to cities-admin1
    mapping so postal codes match the right region. The datasets are
    committed to the repository, so the script only needs to run when a
    refresh is wanted.

data/addresses/

    One JSON file per dataset locale (es_ES, es_MX, es_AR, es_CL, es_CO,
    en_US, en_GB, fr_FR, de_DE, it_IT, pt_BR), each holding up to 300
    cities sorted by population with their postal codes, up to 250
    language-filtered street names, and source attribution. Together
    they weigh under 400 KB.

tests/

    The pytest suite described in Testing, one file per module under
    test. It exercises the real filesystem, the real Faker providers
    and the real datasets, and stubs only the temporary-email API so it
    runs offline.

requirements.txt

    Runtime dependencies: faker, requests, pyperclip, colorama.
    requirements-dev.txt adds the test tooling (pytest) and is only
    needed when running the suite.

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
codes (coverage is 70-98% depending on the country dataset) and up to 250
street names. To regenerate them:

    py -3.13 -X utf8 tools/build_datasets.py

Overpass is rate-limited and occasionally drops queries, so the script caches
all downloads in the system temp directory and retries across several public
mirrors. Use --skip-osm to refresh only the GeoNames part reusing the streets
already on disk, and --sleep to tune the delay between queries.

Dataset gaps: the GeoNames Colombia postal file has no entry for Bogota,
and the Mexico file has no standalone "Ciudad de Mexico" entry, so those
cities keep a null postal code or a code from a matching region variant.
Street names are filtered by language (non-Latin scripts and foreign
first words are dropped), but the country grid cells overlap neighbouring
countries, so a few cross-border names may remain in the France, Germany,
Italy and Brazil datasets. The UK dataset may include some Irish names,
since the two are not distinguishable by word lists. The datasets can be
refreshed or replaced with a country-polygon (area) Overpass query by
editing tools/build_datasets.py.

## Known limitations

The tool is intentionally simple, and two design trade-offs are worth
being explicit about.

Synchronous I/O in the main thread. The email creation and inbox-read
steps call the provider APIs synchronously, so the terminal blocks while
the request is in flight. The impact is bounded: the provider chain falls
back on failure, per-provider usage counters skip a provider before it
rejects the request, --delay throttles script loops, and --email-offline
skips the network entirely. An asynchronous redesign would let the CLI
stay responsive, but it would complicate the codebase for little practical
gain at this scale.

JSON-file persistence. History and usage data are stored as plain JSON
files (history.json, email_usage.json) and exports are CSV or JSON. This
is adequate for personal use and low-volume seeding. Projects that need
to store or query tens of thousands of identities should migrate to a
portable database such as SQLite.

## Possible extensions

The following ideas are starting points for anyone who wants to adapt the
tool to their own needs.

Add a profile picture by calling a text-to-avatar or identicon service
(DiceBear, UI Avatars) with the generated username as the seed, and save
the image alongside the JSON export.

Add a web API mode using Flask or FastAPI so that identities can be
requested over HTTP. This is useful when integrating the generator into
automated testing pipelines or browser automation scripts.

Add a search command that filters history.json by country, date range, or
name substring, which becomes useful once the history grows large.

Add a delete command to remove a specific identity from history by its UUID,
for cases where a generated profile should no longer be stored locally.

Add support for custom locale weights so that, for example, Spanish locales
are picked more often than others when no --locale flag is provided.

Replace the plain-text clipboard format with a structured template that the
user can edit, allowing fields to be reordered or excluded to match a
particular registration form layout.

Make email and inbox operations asynchronous so the CLI stays responsive
while provider requests are in flight (see Known limitations).

Replace the JSON history file with a portable database such as SQLite for
high-volume use (see Known limitations).

Refetch the street datasets with a country-polygon (area) Overpass query
instead of grid cells, which would eliminate the residual cross-border
street names documented in Data sources.

Generate passport numbers with the official per-country serial algorithms
instead of the current plausible formats, once authoritative references
for each country's check digits are available.

## Responsible use

This tool generates data that is completely fictional. It is intended for
privacy protection during online registrations and for software testing
purposes. Using it to impersonate real individuals, commit fraud, bypass
legal identity requirements, or engage in any illegal activity is outside
the intended scope and is the sole responsibility of the user. The authors
provide no warranty and accept no liability for any use of this software.

## License

MIT. See LICENSE for the full text.
