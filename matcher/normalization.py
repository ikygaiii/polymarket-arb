import re
import unicodedata

# Common esports team alias mappings
TEAM_ALIASES = {
    "natus vincere": "navi",
    "faze clan": "faze",
    "g2 esports": "g2",
    "team spirit": "spirit",
    "virtus.pro": "vp",
    "virtus pro": "vp",
    "team liquid": "liquid",
    "astralis": "astralis",
    "mousesports": "mouz",
    "mouz": "mouz",
    "cloud9": "c9",
    "ninjas in pyjamas": "nip",
    "fnatic": "fnatic",
    "og": "og",
    "team secret": "secret",
    "evil geniuses": "eg",
    "t1": "t1",
    "gen.g": "geng",
    "gen g": "geng",
    "edward gaming": "edg",
    "royale never give up": "rng",
}

CYRILLIC_TO_LATIN = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo', 'ж': 'zh',
    'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm', 'н': 'n', 'о': 'o',
    'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u', 'ф': 'f', 'х': 'kh', 'ц': 'ts',
    'ч': 'ch', 'ш': 'sh', 'щ': 'shch', 'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya'
}


def transliterate(text: str) -> str:
    """Translates Cyrillic text to Latin text character by character."""
    res = []
    for char in text.lower():
        res.append(CYRILLIC_TO_LATIN.get(char, char))
    return "".join(res)


def normalize_string(text: str) -> str:
    """Normalizes string for matching: transliterate, lowercase, remove punctuation."""
    if not text:
        return ""
    text = transliterate(text.strip().lower())
    # Remove accents/diacritics
    text = "".join(
        c for c in unicodedata.normalize('NFD', text)
        if unicodedata.category(c) != 'Mn'
    )
    # Strip common prefix/suffix noise
    text = re.sub(r'\b(esports|gaming|team|club)\b', '', text)
    # Remove non-alphanumeric chars
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    # Normalize multiple spaces
    text = " ".join(text.split())
    
    # Apply alias mapping if exact match
    return TEAM_ALIASES.get(text, text)
