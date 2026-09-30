ZALANDO_MARKETPLACES = {
    "zalando.at": "Austria",
    "zalando.be": "Belgium",
    "zalando.bg": "Bulgaria",
    "zalando.hr": "Croatia",
    "zalando.cz": "Czech Republic",
    "zalando.dk": "Denmark",
    "zalando.ee": "Estonia",
    "zalando.fi": "Finland",
    "zalando.fr": "France",
    "zalando.de": "Germany",
    "zalando.gr": "Greece",
    "zalando.hu": "Hungary",
    "zalando.ie": "Ireland",
    "zalando.it": "Italy",
    "zalando.lv": "Latvia",
    "zalando.lt": "Lithuania",
    "zalando.lu": "Luxembourg",
    "zalando.nl": "Netherlands",
    "zalando.no": "Norway",
    "zalando.pl": "Poland",
    "zalando.pt": "Portugal",
    "zalando.ro": "Romania",
    "zalando.sk": "Slovakia",
    "zalando.si": "Slovenia",
    "zalando.es": "Spain",
    "zalando.se": "Sweden",
    "zalando.ch": "Switzerland",
    "zalando.co.uk": "United Kingdom",
}

DOMAIN_TO_CURRENCY = {
    "zalando.at": "EUR",
    "zalando.be": "EUR",
    "zalando.bg": "EUR",
    "zalando.hr": "EUR",
    "zalando.cz": "CZK",
    "zalando.dk": "DKK",
    "zalando.ee": "EUR",
    "zalando.fi": "EUR",
    "zalando.fr": "EUR",
    "zalando.de": "EUR",
    "zalando.gr": "EUR",
    "zalando.hu": "HUF",
    "zalando.ie": "EUR",
    "zalando.it": "EUR",
    "zalando.lv": "EUR",
    "zalando.lt": "EUR",
    "zalando.lu": "EUR",
    "zalando.nl": "EUR",
    "zalando.no": "NOK",
    "zalando.pl": "PLN",
    "zalando.pt": "EUR",
    "zalando.ro": "RON",
    "zalando.sk": "EUR",
    "zalando.si": "EUR",
    "zalando.es": "EUR",
    "zalando.se": "SEK",
    "zalando.ch": "CHF",
    "zalando.co.uk": "GBP",
}

# These storefronts use audience landing paths in navigation, but require a
# localized catalog prefix when a search query is applied.
DOMAIN_SEARCH_PATH_PREFIX = {
    "zalando.hr": "katalog-",
    "zalando.ee": "kataloog-",
    "zalando.hu": "katalogus-",
    "zalando.lv": "katalogs-",
    "zalando.lt": "katalogas-",
    "zalando.pt": "catalogo-",
    "zalando.ro": "catalog-",
    "zalando.sk": "katalog-",
    "zalando.si": "katalog-",
}

# Greek catalog routes use adjective forms that cannot be created by adding a
# prefix to the audience landing paths.
DOMAIN_AUDIENCE_PATH_OVERRIDES = {
    "zalando.gr": {
        "women": "/gynaikeia/",
        "men": "/andrika/",
        "kids": "/paidika/",
    }
}
