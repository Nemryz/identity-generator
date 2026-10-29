# Dataset attribution

The JSON files in this directory hold the real-address data the generator uses for the eleven dataset locales (es_ES, es_MX, es_AR, es_CL, es_CO, en_US, en_GB, fr_FR, de_DE, it_IT, pt_BR): city names with population and coordinates, real street networks with house numbers and real postal codes, plus the admin-to-region mapping that lets a street query prefer the postcode for the city's own region over the plain first match.

They are derived works built by `tools/build_datasets.py` from these sources, and the credit the sources ask for lives in this very file, so it travels with every wheel where the data travels:

- GeoNames (CC-BY 4.0, <https://www.geonames.org/export/>): the cities15000 dump for city names, populations and coordinates, and the postal files for country-level postcode geography.
- OpenStreetMap (c) OpenStreetMap contributors, data available under the Open Database License (ODbL), at <https://www.openstreetmap.org/copyright>: the street networks, queried through the public Overpass API.

If you redistribute these files, or anything that embeds them such as the wheel or a container image, keep this attribution and the links intact, because both licenses require the credit to accompany the derived database rather than to live at the distribution point only. The full license texts at the linked pages control the exact terms; this file is their attribution, not a substitute for them.

Dataset gaps to know about: the GeoNames Colombia postal file has no entry for Bogota without its region name, and the Mexico postal file has no standalone "Ciudad de Mexico" row, cases the builder resolves with documented fallbacks.
