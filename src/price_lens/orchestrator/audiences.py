"""Audience handling across platforms.

Zalando has separate men / women / kids shops, so one query ("sneakers") is run once per
audience shop. Amazon, eBay and MediaMarkt have no such switch: the audience has to be part
of the search phrase ("men's sneakers", "Herren Sneaker", "baskets homme"). This module
builds those phrases per storefront language. Plans can override any phrase via
``query.audience_queries[language][audience]``.
"""
from __future__ import annotations

AUDIENCES = ("men", "women", "kids")

# "{q}" is replaced by the (translated) base query. Word order follows how shoppers search.
AUDIENCE_TEMPLATES: dict[str, dict[str, str]] = {
    "en": {"men": "men's {q}", "women": "women's {q}", "kids": "kids {q}"},
    "de": {"men": "Herren {q}", "women": "Damen {q}", "kids": "Kinder {q}"},
    "fr": {"men": "{q} homme", "women": "{q} femme", "kids": "{q} enfant"},
    "es": {"men": "{q} hombre", "women": "{q} mujer", "kids": "{q} niños"},
    "it": {"men": "{q} uomo", "women": "{q} donna", "kids": "{q} bambino"},
    "nl": {"men": "heren {q}", "women": "dames {q}", "kids": "kinder {q}"},
    "pl": {"men": "{q} męskie", "women": "{q} damskie", "kids": "{q} dziecięce"},
    "sv": {"men": "herr {q}", "women": "dam {q}", "kids": "barn {q}"},
    "da": {"men": "herre {q}", "women": "dame {q}", "kids": "børne {q}"},
    "no": {"men": "herre {q}", "women": "dame {q}", "kids": "barn {q}"},
    "fi": {"men": "miesten {q}", "women": "naisten {q}", "kids": "lasten {q}"},
    "pt": {"men": "{q} masculino", "women": "{q} feminino", "kids": "{q} infantil"},
    "tr": {"men": "erkek {q}", "women": "kadın {q}", "kids": "çocuk {q}"},
    "cs": {"men": "pánské {q}", "women": "dámské {q}", "kids": "dětské {q}"},
    "sk": {"men": "pánske {q}", "women": "dámske {q}", "kids": "detské {q}"},
    "hu": {"men": "férfi {q}", "women": "női {q}", "kids": "gyerek {q}"},
    "ro": {"men": "{q} bărbați", "women": "{q} femei", "kids": "{q} copii"},
    "ja": {"men": "メンズ {q}", "women": "レディース {q}", "kids": "キッズ {q}"},
    "ar": {"men": "{q} رجالي", "women": "{q} نسائي", "kids": "{q} أطفال"},
}


def audience_query(base_query: str, audience: str, language: str,
                   overrides: dict | None = None) -> str:
    """The search phrase for one audience in one storefront language."""
    explicit = ((overrides or {}).get(language) or {}).get(audience)
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    template = AUDIENCE_TEMPLATES.get(language, AUDIENCE_TEMPLATES["en"])[audience]
    return template.replace("{q}", base_query.strip())


def search_audiences(search: dict) -> list[str]:
    """Search-level audiences; older plans kept them on the Zalando target."""
    audiences = search.get("audiences")
    if audiences is None:
        for target in search.get("targets", []):
            if target.get("platform") == "zalando":
                audiences = (target.get("platform_options") or {}).get("audiences")
                break
    return [a for a in AUDIENCES if a in (audiences or [])]
