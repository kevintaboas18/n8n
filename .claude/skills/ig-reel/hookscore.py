#!/usr/bin/env python3
"""
hookscore.py - score the first line of a Reel on the five things strong hooks
have in common, and rank a batch of them against each other.

What this is:  five local heuristics, computed on your machine from the text
alone. They measure properties that hooks which hold attention tend to share -
a length you can say in under three seconds, a concrete marker, something at stake,
the payload at the front rather than the back, and a viewer to aim it at.

What this is NOT:  a view predictor. It was tested against 74 real short-form
hooks, transcribed from the first three seconds of the top eight and bottom
eight performers on five channels. Separating a real hook from a deliberately
bad one it does well: AUC 0.83, and 9 of 10 written-to-be-bad hooks scored
below the real median. Separating a good creator's hits from that same
creator's misses it barely does at all: AUC 0.56, where 0.50 is a coin flip.

So use it for what it measured well. It catches greetings, preambles, hooks
with nothing concrete in them and hooks that take five seconds to say. It will
not tell you which of two decent hooks will travel, and nothing that reads text
can, because that is decided by your face, your edit, your audio and who
Instagram shows it to. Trust the retention graph over this script.

Each check returns 0 to 100. Higher is better.

Usage
  python3 hookscore.py hooks.txt              # one hook per line, ranked
  python3 hookscore.py --hook "I lost $18,000 on one missing contract."
  pbpaste | python3 hookscore.py -
  python3 hookscore.py hooks.txt --json
"""

import argparse
import json
import re
import statistics
import sys
import unicodedata

WORD_RE = re.compile(r"[A-Za-z0-9$%'’-]+")
NUMBER_RE = re.compile(
    r"\$\s?\d[\d,]*(?:\.\d+)?"                       # money, whole
    r"|\b\d[\d,]*(?:\.\d+)?\s?"                      # a figure, with or
    r"(?:%|k\b|x\b|hrs?\b|hours?\b|mins?\b|minutes?\b"  # without a unit
    r"|days?\b|weeks?\b|months?\b|years?\b)?",
    re.IGNORECASE)
PROPER_RE = re.compile(r"(?<!^)\b[A-Z][a-z]{2,}\b")
HASHTAG_RE = re.compile(r"(?:^|\s)#\w+")
EMOJI_RE = re.compile(r"[\U0001F300-\U0001FAFF☀-➿]")

# Spoken hooks say their numbers out loud. "Zero dollars" and "twenty grand"
# are as concrete as "$0" and "$20,000", and counting only digits missed them.
# "one" and "first" are deliberately absent: they are filler far more often
# than they are a quantity.
SPOKEN_NUMBERS = {
    "zero", "two", "three", "four", "five", "six", "seven", "eight", "nine",
    "ten", "eleven", "twelve", "fifteen", "twenty", "thirty", "forty", "fifty",
    "sixty", "seventy", "eighty", "ninety", "hundred", "thousand", "million",
    "billion", "dozen", "half", "twice", "triple",
}
MONEY_WORDS = {
    "dollars", "dollar", "bucks", "grand", "percent", "cents",
    "millionaire", "billionaire", "revenue", "profit", "salary", "rent",
}

# Words that put something on the line. A hook with none of these is a
# statement; a hook with one is a reason to keep watching.
STAKES = {
    "stop", "never", "wrong", "mistake", "mistakes", "lost", "lose", "losing",
    "cost", "costs", "broke", "broken", "failed", "failure", "fail", "nobody",
    "no", "not", "don't", "dont", "doesn't", "didn't", "can't", "won't",
    "quit", "quitting", "fired", "deleted", "delete", "killed", "kills", "kill",
    "replaced", "replaces", "cut", "beat", "free", "paid", "charged", "hired",
    "saved", "first",
    "banned", "illegal", "worst", "hate", "hated", "wasted", "waste", "scam",
    "lie", "lied", "lying", "truth", "secret", "hidden", "stole", "stolen",
    "before", "until", "instead", "but", "except", "unless", "problem",
    "risk", "danger", "warning", "regret", "wish", "should", "shouldn't",
    "still", "already", "only", "without", "versus", "vs", "actually",
}

# Openers that spend the first second saying nothing.
WEAK_OPENERS = [
    "so", "ok", "okay", "hey", "hi", "hello", "guys", "yo", "alright",
    "welcome", "today", "basically", "honestly", "look", "listen", "um",
    "just", "let", "lets", "let's", "i wanted", "i want", "one of",
    "have you", "did you", "do you", "are you", "in this", "in today",
    "the thing", "a lot", "there is", "there are", "this is", "it is",
    "as a", "when it", "if you've", "you know",
]

# Imperatives that earn the front position.
IMPERATIVES = {
    "stop", "steal", "copy", "delete", "try", "watch", "read", "save",
    "use", "build", "make", "write", "send", "take", "start", "quit",
    "never", "always", "don't", "dont", "do", "put", "run", "check",
}

DEALBREAKERS = [
    (re.compile(r"(?i)^\s*(?:stop scrolling|don'?t scroll)"),
     "Opens with \"stop scrolling\". Asking for attention proves you have not earned it."),
    (re.compile(r"(?i)\b(?:in (?:this|today'?s) (?:video|reel)|i'?m going to show you|i'?ll show you how)\b"),
     "Video preamble. Delete it and open on the payoff."),
    (re.compile(r"(?i)^\s*(?:hey |hi |what'?s up |welcome )"),
     "Greeting. Nobody came to the feed to be greeted."),
    (HASHTAG_RE,
     "Hashtag in the hook. Hashtags belong at the bottom of the caption, if anywhere."),
    (EMOJI_RE,
     "Emoji in the hook. On-screen text at hook size has room for words or for an emoji, not both."),
]


def clamp(n):
    return max(0.0, min(100.0, n))


def words(text):
    # "$18,000" is one word when it is spoken, so it is one word here too.
    return WORD_RE.findall(re.sub(r"(?<=\d),(?=\d)", "", text))


def check_length(text):
    """A hook has to land before the thumb moves. Roughly two seconds."""
    w = words(text)
    n = len(w)
    secs = n / 2.75                      # ~165 words per minute, spoken
    chars = len(text.strip())
    if 5 <= n <= 12:
        score = 100.0
    elif n < 5:
        score = clamp(100 - (5 - n) * 20)
    else:
        score = clamp(100 - (n - 12) * 11)
    if chars > 60:                       # two lines of big on-screen text
        score -= 12
    return clamp(score), f"{n} words, {chars} chars, ~{secs:.1f}s spoken (want 5-12 words)"


def check_specificity(text):
    """One concrete thing beats three abstract ones."""
    nums = [n.strip() for n in NUMBER_RE.findall(text) if n.strip()]
    propers = set(PROPER_RE.findall(text))
    low = [w.lower().strip("'’") for w in words(text)]
    spoken = [w for w in low if w in SPOKEN_NUMBERS or w in MONEY_WORDS]
    hits = len(nums) + len(propers) + len(spoken)
    score = 15.0 if hits == 0 else clamp(45 + hits * 30)
    found = ", ".join(nums[:2] + sorted(propers)[:2] + spoken[:2])
    return score, (f"{hits} concrete marker(s)" + (f": {found}" if found else
                   " - no number, no name, nothing checkable"))


def check_stakes(text):
    """Tension, cost, negation. Something the viewer might lose."""
    w = [x.lower().strip("'’") for x in words(text)]
    hits = [x for x in w if x in STAKES]
    markers = sorted(set(hits))
    if re.search(r"\$\s?\d", text):
        markers.append("a price")
    n = len(markers)
    score = {0: 20.0, 1: 70.0}.get(n, 100.0)
    detail = f"{n} tension marker(s)" + (f": {', '.join(markers[:4])}" if markers else
                                         " - nothing is at stake in this line")
    return clamp(score), detail


def check_frontload(text):
    """The interesting word cannot be in position nine."""
    w = words(text)
    if not w:
        return 0.0, "empty"
    low = [x.lower().strip("'’") for x in w]
    opener = " ".join(low[:2])
    penalty = 0
    hit_opener = None
    for weak in WEAK_OPENERS:
        if opener.startswith(weak) or low[0] == weak:
            penalty, hit_opener = 30, weak
            break
    payload = None
    for i, token in enumerate(low):
        if (token in STAKES or token in SPOKEN_NUMBERS or token in MONEY_WORDS
                or NUMBER_RE.match(w[i]) or (i and PROPER_RE.match(w[i]))):
            payload = i
            break
    if payload is None:
        base = 30.0
        where = "no payload word anywhere in the line"
    elif payload <= 3:
        base = 100.0
        where = f"payload at word {payload + 1}"
    elif payload <= 6:
        base = 70.0
        where = f"payload at word {payload + 1}, could move forward"
    else:
        base = 40.0
        where = f"payload at word {payload + 1}, too late"
    detail = where + (f"; weak opener \"{hit_opener}\"" if hit_opener else "")
    return clamp(base - penalty), detail


def check_address(text):
    """Aimed at one viewer, or floating in the air."""
    low = text.lower()
    w = [x.lower().strip("'’") for x in words(text)]
    if re.search(r"\b(you|your|you're|youre|yourself)\b", low):
        return 100.0, "speaks to the viewer"
    if w and w[0] in IMPERATIVES:
        return 90.0, f"imperative opener (\"{w[0]}\")"
    if re.search(r"\b(i|my|me|we|our)\b", low):
        return 70.0, "first person, no viewer named"
    return 35.0, "third person, nobody in the room"


# ---------------------------------------------------------------------------
# Spanish
#
# Added next to the English panel; the English code above is untouched. This is a
# first version, written from how Spanish hooks are usually built and NOT tuned on a
# corpus of real Spanish reels, which the English panel was. Trust it to catch
# greetings, preambles and hooks with nothing concrete in them. Do not read its
# absolute scores as a prediction. Word lists are unaccented because accents are
# stripped before matching (people drop them in captions), and they stay neutral
# between Spain and Latin America where that is cheap.
# ---------------------------------------------------------------------------

def strip_accents(text):
    """Lower-case and drop accents, keeping the n-tilde, so 'Perdí' and 'perdi' match alike."""
    out = []
    for ch in unicodedata.normalize("NFD", text.lower()):
        if unicodedata.category(ch) == "Mn" and ch != "̃":
            continue
        out.append(ch)
    return unicodedata.normalize("NFC", "".join(out))


ES_STOP = {"de", "la", "que", "el", "en", "y", "o", "los", "las", "un", "una", "por", "con", "para", "es",
           "se", "te", "mi", "tu", "lo", "al", "del", "como", "mas", "pero", "sus", "le", "ya", "si", "este",
           "esta", "esto", "muy", "todo", "tus", "mis", "nos", "yo", "porque", "tambien", "sin", "sobre",
           "hay", "ha", "han", "eres", "soy", "estoy", "quiero", "puedo", "tengo", "voy", "va", "vas",
           "cuando", "donde", "quien", "cual", "fue", "hoy", "nadie", "nunca", "siempre", "ahora"}
EN_STOP = {"the", "and", "to", "of", "in", "is", "it", "that", "for", "you", "with", "on", "this", "was",
           "are", "be", "have", "my", "i", "not", "but", "at", "as", "from", "your", "we", "they", "she",
           "what", "how", "when", "because", "so", "do", "does", "did", "just", "about", "if", "or", "an",
           "can", "will", "would", "there", "their", "its", "all", "out", "up", "get", "got", "go", "like"}


def detect_lang(text):
    """'es' or 'en' for one piece of text. Falls back to 'en' when there is no evidence."""
    low = text.lower()
    tokens = [strip_accents(t) for t in re.findall(r"[a-záéíóúüñ]+", low)]
    es = sum(1 for t in tokens if t in ES_STOP)
    es += 3 * sum(low.count(c) for c in "¿¡ñ") + sum(low.count(c) for c in "áéíóúü")
    en = sum(1 for t in tokens if t in EN_STOP)
    return "es" if es > en else "en"


ES_WORD_RE = re.compile(r"[A-Za-z0-9ÁÉÍÓÚÜÑáéíóúüñ$%'’-]+")
ES_NUMBER_RE = re.compile(
    r"\$\s?\d[\d,]*(?:\.\d+)?"                                   # money, whole
    r"|€\s?\d[\d.,]*"
    r"|\b\d[\d.,]*\s?(?:%|€|k\b|x\b|hrs?\b|horas?\b|mins?\b|minutos?\b|d[ií]as?\b|semanas?\b"
    r"|mes(?:es)?\b|a[ñn]os?\b|euros?\b|d[oó]lares\b|pesos\b)?",  # a figure, with or without a unit
    re.IGNORECASE)
ES_PROPER_RE = re.compile(r"(?<![¿¡])(?<![.!?]\s)(?<!^)\b[A-ZÁÉÍÓÚÑ][a-záéíóúüñ]{2,}\b")

ES_SPOKEN_NUMBERS = {
    "cero", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve", "diez", "once", "doce",
    "quince", "veinte", "treinta", "cuarenta", "cincuenta", "sesenta", "setenta", "ochenta", "noventa",
    "cien", "ciento", "mil", "millon", "millones", "docena", "mitad", "doble", "triple",
}
ES_MONEY_WORDS = {
    "dolares", "dolar", "euros", "euro", "pesos", "peso", "lucas", "pavos", "centavos", "centimos",
    "porciento", "millonario", "millonaria", "ingresos", "ganancias", "beneficios", "sueldo", "salario",
    "alquiler", "facturacion", "facturar", "factura",
}
ES_STAKES = {
    "nunca", "jamas", "nadie", "ninguno", "ninguna", "tampoco", "no", "sin", "pero", "excepto", "salvo",
    "solo", "unicamente", "todavia", "ya", "antes", "hasta", "realmente", "cuidado", "ojo", "mal", "peor",
    "perdi", "perdio", "perdiste", "perdimos", "perdieron", "perder", "perdida", "perdidas", "perdido",
    "perdidos", "pierdes", "pierdo", "pierde", "pierden", "perdiendo",
    "costo", "costos", "cuesta", "cuestan", "costar", "costaba", "costaron", "coste", "costes",
    "fracaso", "fracasos", "fracasar", "fracase", "fracasaron", "fracasado", "fracasada",
    "error", "errores", "equivoque", "equivocado", "equivocada", "equivocas", "equivocaron", "equivocarse",
    "roto", "rota", "rotos", "rotas", "rompi", "rompio", "romper", "rompe",
    "falla", "fallas", "fallo", "fallos", "fallar", "fallaron", "falle",
    "borre", "borro", "borrar", "borrado", "eliminar", "elimine", "elimino", "eliminado", "eliminaron",
    "mata", "mato", "matar", "mataron", "reemplazo", "reemplazar", "reemplazaron", "reemplaza",
    "gratis", "gratuito", "gratuita", "pague", "pagar", "pagaba", "pagaste", "pagamos", "pagan", "pagado",
    "cobre", "cobro", "cobrar", "cobraba", "cobrado", "contrate", "contrataron", "contratado",
    "ahorre", "ahorro", "ahorrar", "ahorrado", "despedido", "despedida", "despidieron", "despedir",
    "despedi", "renuncie", "renuncio", "renunciar", "renunciaron", "prohibido", "prohibida", "prohibir",
    "ilegal", "ilegales", "baneado", "baneada", "bloqueado", "bloqueada", "estafa", "estafas", "estafar",
    "estafaron", "mentira", "mentiras", "minti", "mintio", "mentir", "mintieron", "verdad", "secreto",
    "secretos", "oculto", "oculta", "escondido", "robo", "robe", "robar", "robaron", "robado", "riesgo",
    "riesgos", "peligro", "peligros", "peligroso", "advertencia", "arrepiento", "arrepenti", "arrepentido",
    "odio", "odie", "odiar", "desperdicio", "desperdiciar", "desperdicie", "desperdiciado", "problema",
    "problemas", "culpa", "culpable", "miedo", "miedos", "ruina", "arruine", "arruino", "arruinar",
    "arruinado", "quiebra", "quebre", "quebrar", "quebrado", "deuda", "deudas", "deberia", "deberias",
    "deberian", "versus", "vs",
    # The English panel counts "first" ("my first 47 reels did nothing"); these are its Spanish forms.
    "primer", "primero", "primera", "primeros", "primeras", "aun", "ojala",
}
# Spanish conjugates and inflects, so exact forms miss most of what people say. A word also counts
# when it is the plural of a listed one, or starts with one of these stems (minus the exceptions).
ES_STAKES_STEMS = (
    "perd", "pierd", "fracas", "equivoc", "estaf", "arruin", "desperdici", "arrepent", "ahorr", "despid",
    "despedi", "renunci", "prohib", "peligr", "riesg", "problem", "secret", "ocult", "gratuit", "quebr",
    "quiebr", "deud", "romp", "reemplaz", "sustitu", "elimin", "fall", "cobr", "borr",
)
ES_STAKES_NOT = ("perdon", "borrach", "secretari", "rompecab")


def es_is_stake(token):
    forms = {token}
    if token.endswith("s"):
        forms.add(token[:-1])
    if token.endswith("es"):
        forms.add(token[:-2])
    if forms & ES_STAKES:
        return True
    return token.startswith(ES_STAKES_STEMS) and not token.startswith(ES_STAKES_NOT)
# Openers that spend the first second saying nothing. Matched on the first two words.
ES_WEAK_OPENERS = [
    "hola", "buenas", "que tal", "bienvenido", "bienvenida", "hoy", "basicamente", "la verdad", "oye",
    "pues", "bueno", "vale", "ok", "okay", "hey", "chicos", "chicas", "amigos", "amigas", "gente", "familia",
    "en este", "en el video", "en el reel", "en el post", "queria", "quiero hablar", "una de", "uno de",
    "has visto", "sabias", "alguna vez", "esto es", "hay un", "hay una", "asi que", "a ver", "entonces",
    "si ya", "quiero que", "voy a", "vamos a",
]
ES_IMPERATIVES = {
    "deja", "roba", "copia", "borra", "prueba", "mira", "lee", "guarda", "usa", "construye", "haz",
    "escribe", "envia", "manda", "toma", "empieza", "comienza", "renuncia", "nunca", "siempre", "pon",
    "corre", "revisa", "elimina", "olvida", "evita", "cambia", "deten", "espera", "imagina", "piensa",
    "recuerda", "escucha", "observa", "fijate", "no",
}
ES_VIEWER_RE = re.compile(
    r"\b(?:tu|tus|te|ti|contigo|usted|ustedes|vos|vosotros|os|sos|eres|puedes|quieres|tienes|sabes|"
    r"necesitas|debes|haces|ves|crees|piensas|buscas|intentas|ganas|pierdes|sigues|empiezas|vas|"
    r"podes|queres|tenes)\b")
ES_SELF_RE = re.compile(r"\b(?:yo|mi|mis|me|nos|nuestro|nuestra|nuestros|nuestras|conmigo|nosotros|nosotras)\b")
ES_NOT_A_VERB = {"asi", "aqui", "alli", "ahi", "si", "mi", "cafe", "bebe", "comite", "cliche", "taxi", "wifi",
                 "sushi", "kiwi", "bikini", "safari", "ski", "yeti", "mami", "papi", "hindi", "maori"}
# First-person singular forms that carry no accent and cannot be mistaken for anything else, so the
# accent rule in es_check_address cannot see them. Typed with or without accents.
ES_FIRST_PERSON = {"hice", "tuve", "estuve", "supe", "pude", "puse", "quise", "dije", "traje", "vine", "anduve",
                   "fui", "vi", "cai", "crei", "lei", "oi", "soy", "estoy", "voy", "tengo", "hago", "digo",
                   "vengo", "pongo", "salgo", "traigo", "conozco", "quiero", "puedo"}

ES_DEALBREAKERS = [
    (re.compile(r"^\s*[¡¿]?\s*(?:deja(?:d)? de (?:hacer )?scroll\w*|no (?:sigas|hagas|sigan|hagan) "
                r"(?:haciendo )?scroll\w*|para de (?:hacer )?scroll\w*|no scrollees|no pases de largo)"), False,
     "Opens with \"stop scrolling\". Asking for attention proves you have not earned it."),
    (re.compile(r"\b(?:en (?:este|el) (?:video|reel)(?: de hoy)?|hoy (?:te )?voy a "
                r"(?:mostrar|ensenar|contar|explicar)|(?:te )?voy a (?:mostrar|ensenar)(?:te)?(?: como)?|"
                r"voy a (?:mostrarte|ensenarte|contarte|explicarte))\b"), False,
     "Video preamble. Delete it and open on the payoff."),
    (re.compile(r"^\s*[¡¿]?\s*(?:hola+|buenas|que tal|bienvenid[oa]s?|hey|buen[oa]s (?:dias|tardes|noches))\b"),
     False, "Greeting. Nobody came to the feed to be greeted."),
    (HASHTAG_RE, True, "Hashtag in the hook. Hashtags belong at the bottom of the caption, if anywhere."),
    (EMOJI_RE, True, "Emoji in the hook. On-screen text at hook size has room for words or for an emoji, "
                     "not both."),
]


def es_words(text):
    """18.000 and 1,5 are each one spoken number, so the separator is dropped before splitting."""
    return ES_WORD_RE.findall(re.sub(r"(?<=\d)[.,](?=\d)", "", text))


def es_check_length(text):
    """Spanish runs about a fifth longer than English for the same content, so the window is wider."""
    n = len(es_words(text))
    secs = n / 2.75
    chars = len(text.strip())
    if 5 <= n <= 14:
        score = 100.0
    elif n < 5:
        score = clamp(100 - (5 - n) * 20)
    else:
        score = clamp(100 - (n - 14) * 11)
    if chars > 72:
        score -= 12
    return clamp(score), f"{n} words, {chars} chars, ~{secs:.1f}s spoken (want 5-14 words)"


def es_check_specificity(text):
    nums = [n.strip().rstrip(".,") for n in ES_NUMBER_RE.findall(text) if n.strip()]
    nums = [n for n in nums if n]
    propers = set(ES_PROPER_RE.findall(text))
    low = [strip_accents(w).strip("'’") for w in es_words(text)]
    spoken = [w for w in low if w in ES_SPOKEN_NUMBERS or w in ES_MONEY_WORDS]
    hits = len(nums) + len(propers) + len(spoken)
    score = 15.0 if hits == 0 else clamp(45 + hits * 30)
    found = ", ".join(nums[:2] + sorted(propers)[:2] + spoken[:2])
    return score, (f"{hits} concrete marker(s)" + (f": {found}" if found else
                   " - no number, no name, nothing checkable"))


def es_check_stakes(text):
    w = [strip_accents(x).strip("'’") for x in es_words(text)]
    markers = sorted(set(x for x in w if es_is_stake(x)))
    if re.search(r"\$\s?\d|€\s?\d|\d\s?€", text):
        markers.append("a price")
    n = len(markers)
    score = {0: 20.0, 1: 70.0}.get(n, 100.0)
    detail = f"{n} tension marker(s)" + (f": {', '.join(markers[:4])}" if markers else
                                         " - nothing is at stake in this line")
    return clamp(score), detail


def es_check_frontload(text):
    w = es_words(text)
    if not w:
        return 0.0, "empty"
    low = [strip_accents(x).strip("'’") for x in w]
    opener = " ".join(low[:2])
    penalty, hit_opener = 0, None
    for weak in ES_WEAK_OPENERS:
        if opener.startswith(weak) or low[0] == weak:
            penalty, hit_opener = 30, weak
            break
    payload = None
    for i, token in enumerate(low):
        if (es_is_stake(token) or token in ES_SPOKEN_NUMBERS or token in ES_MONEY_WORDS
                or ES_NUMBER_RE.match(w[i]) or (i and re.match(r"[A-ZÁÉÍÓÚÑ][a-záéíóúüñ]{2,}$", w[i]))):
            payload = i
            break
    if payload is None:
        base, where = 30.0, "no payload word anywhere in the line"
    elif payload <= 3:
        base, where = 100.0, f"payload at word {payload + 1}"
    elif payload <= 6:
        base, where = 70.0, f"payload at word {payload + 1}, could move forward"
    else:
        base, where = 40.0, f"payload at word {payload + 1}, too late"
    detail = where + (f"; weak opener \"{hit_opener}\"" if hit_opener else "")
    return clamp(base - penalty), detail


def es_check_address(text):
    low = strip_accents(text)
    w = [strip_accents(x).strip("'’") for x in es_words(text)]
    if ES_VIEWER_RE.search(low):
        return 100.0, "speaks to the viewer"
    if w and w[0] in ES_IMPERATIVES:
        return 90.0, f"imperative opener (\"{w[0]}\")"
    # A first-person past tense ends in an accented é/í (perdí, gané). People drop the accent, and an
    # unaccented -i ending is still safe to read as a verb (perdi), but an unaccented -e is not (gane).
    spoken_self = [t for t in re.findall(r"[a-záéíóúüñ]+", text.lower())
                   if (len(t) > 3 and t[-1] in "éíi" and strip_accents(t) not in ES_NOT_A_VERB)
                   or strip_accents(t) in ES_FIRST_PERSON]
    if ES_SELF_RE.search(low) or spoken_self:
        return 70.0, "first person, no viewer named"
    return 35.0, "third person, nobody in the room"


def es_flags(text):
    low = strip_accents(text)
    return [msg for pattern, on_original, msg in ES_DEALBREAKERS
            if pattern.search(text if on_original else low)]


CHECKS = ["LENGTH", "SPECIFICITY", "STAKES", "FRONTLOAD", "ADDRESS"]


def run(text, lang="en"):
    if lang == "es":
        results = {
            "LENGTH": es_check_length(text),
            "SPECIFICITY": es_check_specificity(text),
            "STAKES": es_check_stakes(text),
            "FRONTLOAD": es_check_frontload(text),
            "ADDRESS": es_check_address(text),
        }
        flags = es_flags(text)
    else:
        results = {
            "LENGTH": check_length(text),
            "SPECIFICITY": check_specificity(text),
            "STAKES": check_stakes(text),
            "FRONTLOAD": check_frontload(text),
            "ADDRESS": check_address(text),
        }
        flags = [msg for pattern, msg in DEALBREAKERS if pattern.search(text)]
    scores = [results[c][0] for c in CHECKS]
    # The weakest property caps the hook, same logic as detect.py: one bad
    # property is enough for the thumb to keep moving.
    overall = statistics.mean(scores) * 0.6 + min(scores) * 0.4 - len(flags) * 15
    overall = clamp(overall)
    verdict = "STRONG" if overall >= 70 and min(scores) >= 55 and not flags else (
        "OK" if overall >= 50 else "WEAK")
    return results, overall, verdict, flags


def bar(score, width=24):
    filled = round(score / 100 * width)
    return "#" * filled + "." * (width - filled)


def render_one(text, results, overall, verdict, flags, out=sys.stdout):
    print("\nHOOK SCORE", file=out)
    print("=" * 62, file=out)
    print(f"  \"{text.strip()}\"\n", file=out)
    for name in CHECKS:
        score, detail = results[name]
        print(f"  {name:<13} {bar(score)} {score:5.1f}", file=out)
        print(f"  {'':<13} {detail}", file=out)
    print("-" * 62, file=out)
    print(f"  {'HOOK SCORE':<13} {bar(overall)} {overall:5.1f}   {verdict}", file=out)
    for f in flags:
        print(f"\n  DEALBREAKER  {f}", file=out)
    if verdict != "STRONG":
        weakest = min(CHECKS, key=lambda c: results[c][0])
        print(f"\n  Weakest property: {weakest}. Fix that one and re-run.", file=out)
    print("", file=out)


def render_table(rows, out=sys.stdout):
    print("\nHOOK RANKING\n" + "=" * 78, file=out)
    for i, r in enumerate(rows, 1):
        mark = "->" if i == 1 else "  "
        hook = r["hook"] if len(r["hook"]) <= 62 else r["hook"][:59] + "..."
        print(f"{mark} {r['score']:5.1f} {r['verdict']:<7} {hook}", file=out)
        print(f"        weakest: {r['weakest']} ({r['checks'][r['weakest']]['score']:.0f})", file=out)
        for f in r["flags"]:
            print(f"        dealbreaker: {f}", file=out)
    print("\nShoot the top one. If the top one is under 50, none of these are the hook.\n",
          file=out)


def main():
    ap = argparse.ArgumentParser(description="Score a Reel hook on five properties.")
    ap.add_argument("input", nargs="?", default="-", help="file with one hook per line, or -")
    ap.add_argument("--hook", help="score a single hook given on the command line")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--lang", choices=["auto", "en", "es"], default="auto",
                    help="language of the hooks (default: detect it for each hook)")
    args = ap.parse_args()

    if args.hook:
        lines = [args.hook]
    else:
        raw = sys.stdin.read() if args.input == "-" else open(args.input, encoding="utf-8").read()
        lines = [l.strip() for l in raw.splitlines() if l.strip()]
    if not lines:
        print("nothing to score", file=sys.stderr)
        sys.exit(2)

    langs = [args.lang if args.lang != "auto" else detect_lang(line) for line in lines]
    if "es" in langs:
        print(f"language: {langs.count('es')} Spanish, {langs.count('en')} English "
              f"({'forced' if args.lang != 'auto' else 'detected'})", file=sys.stderr)

    payload = []
    for line, lang in zip(lines, langs):
        results, overall, verdict, flags = run(line, lang)
        payload.append({
            "hook": line,
            "checks": {k: {"score": round(v[0], 1), "detail": v[1]} for k, v in results.items()},
            "weakest": min(CHECKS, key=lambda c: results[c][0]),
            "flags": flags,
            "score": round(overall, 1),
            "verdict": verdict,
        })
        if lang == "es":
            payload[-1]["lang"] = "es"

    if args.json:
        print(json.dumps(payload if len(payload) > 1 else payload[0], indent=2, ensure_ascii=False))
        return

    if len(payload) == 1:
        results, overall, verdict, flags = run(lines[0], langs[0])
        render_one(lines[0], results, overall, verdict, flags)
    else:
        render_table(sorted(payload, key=lambda r: -r["score"]))

    sys.exit(0 if max(p["score"] for p in payload) >= 70 else 1)


if __name__ == "__main__":
    main()
