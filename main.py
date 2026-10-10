"""
main.py

I am the launcher that keeps `python -X utf8 main.py` working exactly as it always did, now that the real code lives in the identity_generator package, which means an installed copy exposes the same entry point through the identity-generator command instead of asking people to import modules by path.

I do nothing else: I hand straight over to the package so there is a single implementation and no second copy to keep in sync.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from identity_generator.main import main  # noqa: E402

if __name__ == "__main__":
    main()