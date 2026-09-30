"""Planning defaults, not language detection. Multilingual storefronts need explicit choice."""

COUNTRY_LANGUAGES = {
    "United States": "en", "United Kingdom": "en", "Germany": "de", "Austria": "de",
    "Japan": "ja", "India": "en", "France": "fr", "Spain": "es", "Italy": "it",
    "Canada": "en", "Mexico": "es", "Brazil": "pt", "Australia": "en",
    "Netherlands": "nl", "Sweden": "sv", "Poland": "pl", "Singapore": "en",
    "Turkey": "tr", "United Arab Emirates": "ar", "Saudi Arabia": "ar",
    "Belgium": "nl", "Egypt": "ar", "Ireland": "en", "Bulgaria": "bg",
    "Croatia": "hr", "Czech Republic": "cs", "Denmark": "da", "Estonia": "et",
    "Finland": "fi", "Greece": "el", "Hungary": "hu", "Latvia": "lv",
    "Lithuania": "lt", "Luxembourg": "fr", "Norway": "no", "Portugal": "pt",
    "Romania": "ro", "Slovakia": "sk", "Slovenia": "sl", "Switzerland": "de",
}


def language_options(domain, country):
    default = COUNTRY_LANGUAGES[country.split(" (", 1)[0]]
    if domain.endswith(".ch"):
        return ["de", "fr", "it"]
    if domain.endswith(".be"):
        return ["nl", "fr"]
    if domain.endswith(".ca"):
        return ["en", "fr"]
    if domain.endswith((".ae", ".sa", ".eg")):
        return ["ar", "en"]
    return [default]
