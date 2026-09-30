# ─────────────────────────────────────────────────────────────────────────────

AMAZON_DOMAINS = {
    "amazon.com":      "United States",
    "amazon.co.uk":    "United Kingdom",
    "amazon.de":       "Germany",
    "amazon.co.jp":    "Japan",
    "amazon.in":       "India",
    "amazon.fr":       "France",
    "amazon.es":       "Spain",
    "amazon.it":       "Italy",
    "amazon.ca":       "Canada",
    "amazon.com.mx":   "Mexico",
    "amazon.com.br":   "Brazil",
    "amazon.com.au":   "Australia",
    "amazon.nl":       "Netherlands",
    "amazon.se":       "Sweden",
    "amazon.pl":       "Poland",
    "amazon.sg":       "Singapore",
    "amazon.com.tr":   "Turkey",
    "amazon.ae":       "United Arab Emirates",
    "amazon.sa":       "Saudi Arabia",
    "amazon.com.be":   "Belgium",
    "amazon.eg":       "Egypt",
}

DOMAIN_TO_CCY = {
    "amazon.com":      "USD",
    "amazon.co.uk":    "GBP",
    "amazon.de":       "EUR",
    "amazon.co.jp":    "JPY",
    "amazon.in":       "INR",
    "amazon.fr":       "EUR",
    "amazon.es":       "EUR",
    "amazon.it":       "EUR",
    "amazon.ca":       "CAD",
    "amazon.com.mx":   "MXN",
    "amazon.com.br":   "BRL",
    "amazon.com.au":   "AUD",
    "amazon.nl":       "EUR",
    "amazon.se":       "SEK",
    "amazon.pl":       "PLN",
    "amazon.sg":       "SGD",
    "amazon.com.tr":   "TRY",
    "amazon.ae":       "AED",
    "amazon.sa":       "SAR",
    "amazon.com.be":   "EUR",
    "amazon.eg":       "EGP",
}

FX_TO_USD = {
    "USD": 1.0,    "EUR": 1.167,  "GBP": 1.364,
    "CAD": 0.731,  "AUD": 0.6495, "JPY": 0.006883,
    "INR": 0.0114, "SEK": 0.1051, "PLN": 0.2679,
    "TRY": 0.0197, "AED": 0.2723, "SAR": 0.2667,
    "EGP": 0.0194, "SGD": 0.7857, "BRL": 0.1696,
    "MXN": 0.0530,
}

# ── Symbol → currency mapping ─────────────────────────────────────────────────
# For unambiguous symbols, maps directly to a currency code.
# Ambiguous symbols (e.g. "$") are resolved using the domain as a tiebreaker.
SYMBOL_TO_CCY_UNAMBIGUOUS = {
    "£":    "GBP",
    "€":    "EUR",
    "¥":    "JPY",   # also CNY but Amazon CN not in scope
    "₹":    "INR",
    "zł":   "PLN",
    "kr":   "SEK",   # also NOK/DKK but not in scope
    "kr.":  "SEK",
    "SEK":  "SEK",
    "₺":    "TRY",
    "TL":   "TRY",
    "د.إ":  "AED",
    "AED":  "AED",
    "﷼":    "SAR",
    "SAR":  "SAR",
    "ر.س":  "SAR",
    "ج.م":  "EGP",
    "EGP":  "EGP",
    "S$":   "SGD",
    "SGD":  "SGD",
    "R$":   "BRL",
    "BRL":  "BRL",
    "MX$":  "MXN",
    "MXN":  "MXN",
    "CA$":  "CAD",
    "C$":   "CAD",
    "CAD":  "CAD",
    "AU$":  "AUD",
    "A$":   "AUD",
    "AUD":  "AUD",
    "USD":  "USD",
}

# Domains where bare "$" means something other than USD
DOLLAR_DOMAIN_CCY = {
    "amazon.ca":       "CAD",
    "amazon.com.au":   "AUD",
    "amazon.sg":       "SGD",
    "amazon.com.mx":   "MXN",   # MX$ but sometimes bare $
}

ACCESSORY_KEYWORDS = [
    "case",
    "mount",
    "battery",
    "charger",
    "stand",
    "cable",
    "pouch",
    "holder",
    "adapter",
]


# ── Default postal codes for "Deliver to" location per domain ────────────────
# These are typical central / capital city postcodes for each marketplace.
# You can override them in the UI.
DOMAIN_DEFAULT_POSTCODE = {
    "amazon.com":      "10001",     # New York, NY
    "amazon.co.uk":    "W1A 1AA",   # London
    "amazon.de":       "10115",     # Berlin
    "amazon.co.jp":    "100-0001",  # Tokyo
    "amazon.in":       "110001",    # New Delhi
    "amazon.fr":       "75001",     # Paris
    "amazon.es":       "28001",     # Madrid
    "amazon.it":       "00118",     # Rome
    "amazon.ca":       "M5H 2N2",   # Toronto
    "amazon.com.mx":   "06600",     # Mexico City
    "amazon.com.br":   "01310-100", # São Paulo
    "amazon.com.au":   "2000",      # Sydney
    "amazon.nl":       "1011 AB",   # Amsterdam
    "amazon.se":       "111 20",    # Stockholm
    "amazon.pl":       "00-001",    # Warsaw
    "amazon.sg":       "048583",    # Singapore
    "amazon.com.tr":   "34000",     # Istanbul
    "amazon.ae":       "00000",     # Dubai (AE has no postal codes; use 00000)
    "amazon.sa":       "11564",     # Riyadh
    "amazon.com.be":   "1000",      # Brussels
    "amazon.eg":       "11511",     # Cairo
}
