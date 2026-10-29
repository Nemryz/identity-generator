# identity_generator I am the package behind the identity-generator command-line tool, and importing me is enough to generate identities without touching the terminal at all. The public surface is small on purpose: generate_identity() returns one coherent profile, set_seed() makes a run reproducible, locale_capabilities() describes what a locale yields, and IDENTITY_SCHEMA is the machine-readable contract of the output. Everything else in the package (history, exporters, email providers, logging and paths) is an implementation detail of the CLI and can change without a deprecation period.

from identity_generator.generator import (
    generate_identity,
    get_supported_locales,
    is_supported_locale,
    locale_capabilities,
    set_seed,
)
from identity_generator.paths import output_dir, user_data_dir
from identity_generator.schema import IDENTITY_SCHEMA, schema_json

__version__ = "1.0.0"

__all__ = [
    "IDENTITY_SCHEMA",
    "__version__",
    "generate_identity",
    "get_supported_locales",
    "is_supported_locale",
    "locale_capabilities",
    "output_dir",
    "schema_json",
    "set_seed",
    "user_data_dir",
]