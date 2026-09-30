"""Offline translations of common exclude words (accessories, parts, condition).

Keyword filters are case-insensitive *substring* matches on listing titles, so entries
are chosen to be distinctive (e.g. Portuguese "capa" alone would also match "capacidade").
Suggestions are shown to the analyst for review before they are added.
"""
from __future__ import annotations

# concept -> language -> words
TERMS: dict[str, dict[str, list[str]]] = {
    "case": {
        "en": ["case"], "de": ["hülle", "schutzhülle"], "fr": ["coque", "étui"],
        "es": ["funda", "carcasa"], "it": ["custodia"], "nl": ["hoesje", "hoes"],
        "pl": ["etui", "pokrowiec"], "sv": ["fodral", "mobilskal"], "da": ["etui", "cover"],
        "no": ["deksel", "etui"], "fi": ["suojakuori", "kotelo"], "cs": ["pouzdro"],
        "sk": ["puzdro"], "pt": ["capa para", "capinha"], "tr": ["kılıf"],
        "hu": ["telefontok", "védőtok"], "ro": ["husa", "husă"],
    },
    "cover": {
        "en": ["cover"], "de": ["cover"], "fr": ["housse"], "es": ["cubierta"],
        "it": ["cover"], "nl": ["cover"], "pl": ["osłona"], "sv": ["skydd"],
        "da": ["cover"], "no": ["deksel"], "fi": ["suojus"], "cs": ["kryt"], "sk": ["kryt"],
        "pt": ["capa protetora"], "tr": ["kapak"], "hu": ["borító"], "ro": ["carcasă"],
    },
    "screen protector": {
        "en": ["screen protector", "tempered glass"], "de": ["schutzfolie", "panzerglas"],
        "fr": ["protection d'écran", "verre trempé"], "es": ["protector de pantalla", "cristal templado"],
        "it": ["pellicola", "vetro temperato"], "nl": ["screenprotector", "beschermglas"],
        "pl": ["folia ochronna", "szkło hartowane"], "sv": ["skärmskydd"], "da": ["skærmbeskytter"],
        "no": ["skjermbeskytter"], "fi": ["näytönsuoja"], "cs": ["ochranné sklo", "ochranná fólie"],
        "sk": ["ochranné sklo"], "pt": ["película"], "tr": ["ekran koruyucu"],
        "hu": ["kijelzővédő"], "ro": ["folie de protecție", "folie protectie"],
    },
    "charger": {
        "en": ["charger"], "de": ["ladegerät", "netzteil"], "fr": ["chargeur"],
        "es": ["cargador"], "it": ["caricabatterie", "caricatore"], "nl": ["oplader"],
        "pl": ["ładowarka"], "sv": ["laddare"], "da": ["oplader"], "no": ["lader"],
        "fi": ["laturi"], "cs": ["nabíječka"], "sk": ["nabíjačka"], "pt": ["carregador"],
        "tr": ["şarj aleti"], "hu": ["töltő"], "ro": ["încărcător", "incarcator"],
    },
    "cable": {
        "en": ["cable"], "de": ["kabel", "ladekabel"], "fr": ["câble"], "es": ["cable"],
        "it": ["cavo"], "nl": ["kabel"], "pl": ["kabel"], "sv": ["kabel"], "da": ["kabel"],
        "no": ["kabel"], "fi": ["kaapeli"], "cs": ["kabel"], "sk": ["kábel"], "pt": ["cabo"],
        "tr": ["kablo"], "hu": ["kábel"], "ro": ["cablu"],
    },
    "adapter": {
        "en": ["adapter"], "de": ["adapter"], "fr": ["adaptateur"], "es": ["adaptador"],
        "it": ["adattatore"], "nl": ["adapter"], "pl": ["adapter"], "sv": ["adapter"],
        "da": ["adapter"], "no": ["adapter"], "fi": ["adapteri", "sovitin"], "cs": ["adaptér"],
        "sk": ["adaptér"], "pt": ["adaptador"], "tr": ["adaptör"], "hu": ["adapter"],
        "ro": ["adaptor"],
    },
    "holder": {
        "en": ["holder", "mount"], "de": ["halterung", "halter"], "fr": ["support téléphone", "support voiture"],
        "es": ["soporte para"], "it": ["supporto per"], "nl": ["houder"], "pl": ["uchwyt"],
        "sv": ["hållare"], "da": ["holder"], "no": ["holder"], "fi": ["pidike"],
        "cs": ["držák"], "sk": ["držiak"], "pt": ["suporte para"], "tr": ["tutucu"],
        "hu": ["tartó"], "ro": ["suport telefon", "suport auto"],
    },
    "bag": {
        "en": ["bag", "pouch"], "de": ["tasche"], "fr": ["sacoche", "pochette"],
        "es": ["bolsa"], "it": ["borsa"], "nl": ["draagtas", "laptoptas"], "pl": ["torba"], "sv": ["väska"],
        "da": ["taske"], "no": ["veske"], "fi": ["laukku"], "cs": ["taška"], "sk": ["taška"],
        "pt": ["bolsa"], "tr": ["çanta"], "hu": ["táska"], "ro": ["geantă", "geanta"],
    },
    "strap": {
        "en": ["strap", "watch band"], "de": ["armband", "ersatzarmband"], "fr": ["bracelet"],
        "es": ["correa"], "it": ["cinturino"], "nl": ["bandje"], "pl": ["pasek"],
        "sv": ["armband"], "da": ["urrem"], "no": ["reim"], "fi": ["ranneke"],
        "cs": ["řemínek"], "sk": ["remienok"], "pt": ["pulseira"], "tr": ["kordon"],
        "hu": ["szíj"], "ro": ["curea"],
    },
    "spare part": {
        "en": ["spare part", "replacement"], "de": ["ersatzteil"], "fr": ["pièce détachée"],
        "es": ["repuesto"], "it": ["ricambio"], "nl": ["onderdeel"], "pl": ["część zamienna"],
        "sv": ["reservdel"], "da": ["reservedel"], "no": ["reservedel"], "fi": ["varaosa"],
        "cs": ["náhradní díl"], "sk": ["náhradný diel"], "pt": ["peça de reposição"],
        "tr": ["yedek parça"], "hu": ["alkatrész"], "ro": ["piesă de schimb"],
    },
    "refurbished": {
        "en": ["refurbished"], "de": ["generalüberholt", "refurbished"], "fr": ["reconditionné"],
        "es": ["reacondicionado"], "it": ["ricondizionato"], "nl": ["refurbished"],
        "pl": ["odnowiony"], "sv": ["renoverad"], "da": ["renoveret"], "no": ["refurbished"],
        "fi": ["kunnostettu"], "cs": ["repasovaný"], "sk": ["repasovaný"],
        "pt": ["recondicionado"], "tr": ["yenilenmiş"], "hu": ["felújított"],
        "ro": ["recondiționat", "reconditionat"],
    },
    "used": {
        "en": ["used", "pre-owned"], "de": ["gebraucht"], "fr": ["d'occasion"],
        "es": ["usado"], "it": ["usato"], "nl": ["gebruikt", "tweedehands"],
        "pl": ["używany"], "sv": ["begagnad"], "da": ["brugt"], "no": ["brukt"],
        "fi": ["käytetty"], "cs": ["použitý"], "sk": ["použitý"], "pt": ["usado"],
        "tr": ["ikinci el"], "hu": ["használt"], "ro": ["folosit", "second hand"],
    },
    "stand": {
        "en": ["stand"], "de": ["ständer"], "fr": ["socle"], "es": ["base de soporte"],
        "it": ["base di supporto"], "nl": ["standaard"], "pl": ["podstawka"], "sv": ["ställ"],
        "da": ["stander"], "no": ["stativ"], "fi": ["teline"], "cs": ["stojan"],
        "sk": ["stojan"], "pt": ["base de apoio"], "tr": ["stand"], "hu": ["állvány"],
        "ro": ["stand"],
    },
}

SUPPORTED_LANGUAGES = sorted({lang for words in TERMS.values() for lang in words})

# Every known word (any language) -> its concept, so "hülle" or "etui" work as input too.
_WORD_TO_CONCEPT = {
    word.lower(): concept
    for concept, by_lang in TERMS.items()
    for words in by_lang.values()
    for word in words
}
_WORD_TO_CONCEPT.update({concept: concept for concept in TERMS})


def suggest_translations(words: list[str], languages: list[str]) -> tuple[dict[str, list[str]], list[str]]:
    """Return ({word: [new translations]}, [words we have no translation for])."""
    existing = {w.strip().lower() for w in words if w.strip()}
    suggestions: dict[str, list[str]] = {}
    unknown: list[str] = []
    for word in dict.fromkeys(w.strip().lower() for w in words if w.strip()):
        concept = _WORD_TO_CONCEPT.get(word)
        if concept is None:
            unknown.append(word)
            continue
        new = [
            candidate
            for lang in languages
            for candidate in TERMS[concept].get(lang, [])
            if candidate.lower() not in existing
        ]
        new = list(dict.fromkeys(new))
        if new:
            suggestions[word] = new
            existing.update(new)
    return suggestions, unknown


def known_concepts() -> list[str]:
    return sorted(TERMS)
