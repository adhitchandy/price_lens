from __future__ import annotations

MEDIAMARKT_MARKETPLACES = {
    "mediamarkt.de": "Germany",
    "mediamarkt.at": "Austria",
    "mediamarkt.ch": "Switzerland",
    "mediamarkt.es": "Spain",
    "mediamarkt.nl": "Netherlands",
    "mediamarkt.be": "Belgium",
    "mediamarkt.pl": "Poland",
    "mediamarkt.hu": "Hungary",
    "mediamarkt.pt": "Portugal (redirects to Darty; unavailable)",
    "mediamarkt.com.tr": "Turkey",
    "mediaworld.it": "Italy",
}

DOMAIN_TO_CURRENCY = {
    "mediamarkt.de": "EUR",
    "mediamarkt.at": "EUR",
    "mediamarkt.ch": "CHF",
    "mediamarkt.es": "EUR",
    "mediamarkt.nl": "EUR",
    "mediamarkt.be": "EUR",
    "mediamarkt.pl": "PLN",
    "mediamarkt.hu": "HUF",
    "mediamarkt.pt": "EUR",
    "mediamarkt.com.tr": "TRY",
    "mediaworld.it": "EUR",
}

DOMAIN_TO_LANGUAGE_PATH = {
    "mediamarkt.de": "de",
    "mediamarkt.at": "de",
    "mediamarkt.ch": "de",
    "mediamarkt.es": "es",
    "mediamarkt.nl": "nl",
    "mediamarkt.be": "nl",
    "mediamarkt.pl": "pl",
    "mediamarkt.hu": "hu",
    "mediamarkt.pt": "pt",
    "mediamarkt.com.tr": "tr",
    "mediaworld.it": "it",
}

# Configured does not mean live-verified. Never follow this change of retailer silently.
UNAVAILABLE_MARKETPLACES = {
    "mediamarkt.pt": "Redirects to darty.pt; a separate Darty adapter is required."
}
