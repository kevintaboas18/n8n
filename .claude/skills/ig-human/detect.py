#!/usr/bin/env python3
"""
detect.py - a five-check panel that scores how machine-written a draft looks.

What this is:  five local heuristics modelled on the signals public AI
detectors actually measure - sentence-length variation, concreteness, stock
vocabulary, typographic fingerprint, and voice. Every score is computed on
your machine from the text alone. Nothing is uploaded.

What this is NOT:  GPTZero, Originality, Copyleaks, Winston or Turnitin.
It does not call their APIs and it cannot promise their verdict. It catches
the things they all key on, which is why fixing them tends to move their
numbers too - but the only honest claim is the one on this line.

Each check returns a HUMAN score from 0 to 100. Higher is better.

Usage
  python3 detect.py draft.txt
  pbpaste | python3 detect.py -
  python3 detect.py draft.txt --json
  python3 detect.py before.txt after.txt      # compare two drafts
  python3 detect.py borrador.txt --lang es    # Spanish is detected on its own; this forces it
"""

import argparse
import json
import os
import re
import statistics
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
LEX = os.path.join(HERE, "slop.json")

SENT_RE = re.compile(r"[^.!?\n]+[.!?]*")
WORD_RE = re.compile(r"[A-Za-z']+")
CONTRACTIONS = re.compile(r"\b\w+'(?:s|t|re|ve|ll|d|m)\b", re.IGNORECASE)
PRONOUNS = re.compile(r"\b(i|me|my|mine|we|us|our|you|your)\b", re.IGNORECASE)
NUMBERS = re.compile(r"\b\d[\d,.]*%?\b|\$\d")
PROPER = re.compile(r"(?<![.!?]\s)(?<!^)\b[A-Z][a-z]{2,}\b", re.MULTILINE)


def clamp(n):
    return max(0.0, min(100.0, n))


def scale(value, human, machine):
    """Map value onto 0-100 where `human` -> 100 and `machine` -> 0."""
    if human == machine:
        return 50.0
    return clamp((value - machine) / (human - machine) * 100)


def sentences(text):
    return [s.strip() for s in SENT_RE.findall(text) if len(s.split()) > 2]


def words(text):
    return WORD_RE.findall(text)


def check_burstiness(text):
    """Humans vary sentence length hard. Models write even."""
    lens = [len(s.split()) for s in sentences(text)]
    if len(lens) < 4:
        return 50.0, "too short to judge"
    mean = statistics.mean(lens)
    cv = statistics.pstdev(lens) / mean if mean else 0
    score = scale(cv, human=0.70, machine=0.22)
    return score, f"variation {cv:.2f} across {len(lens)} sentences (want 0.55+)"


def check_specificity(text):
    """Numbers, names and concrete nouns. Slop is abstract."""
    w = words(text)
    if len(w) < 25:
        return 50.0, "too short to judge"
    per100 = 100 / len(w)
    hits = len(NUMBERS.findall(text)) + len(set(PROPER.findall(text)))
    density = hits * per100
    score = scale(density, human=6.0, machine=0.5)
    return score, f"{hits} concrete markers, {density:.1f} per 100 words (want 4+)"


def check_slop(text, lex):
    """Stock vocabulary density against the lexicon."""
    w = words(text)
    if not w:
        return 50.0, "empty"
    hits, found = 0, []
    for entry in lex["words"] + lex["phrases"]:
        pattern = re.compile(r"\b" + re.escape(entry["find"]).replace(r"\ ", r"\s+") + r"\b",
                             re.IGNORECASE)
        n = len(pattern.findall(text))
        if n:
            hits += n
            found.append(entry["find"])
    density = hits * 100 / len(w)
    score = scale(density, human=0.0, machine=4.0)
    detail = f"{hits} stock terms, {density:.1f} per 100 words"
    if found:
        detail += " (" + ", ".join(sorted(found)[:4]) + (", ..." if len(found) > 4 else "") + ")"
    return score, detail


def check_fingerprint(text):
    """Characters a phone keyboard does not produce."""
    invisible = sum(1 for c in text if unicodedata.category(c) == "Cf")
    em = text.count("—")
    curly = sum(text.count(c) for c in "‘’“”")
    ellip = text.count("…")
    nbsp = sum(text.count(c) for c in "   ")
    total = invisible * 4 + em * 2 + curly + ellip + nbsp
    per1k = total * 1000 / max(len(text), 1)
    score = scale(per1k, human=0.0, machine=12.0)
    detail = (f"{invisible} invisible, {em} em dash, {curly} curly quote, "
              f"{ellip} ellipsis, {nbsp} hard space")
    return score, detail


def check_voice(text, lex):
    """Contractions, person, and the shapes models default to."""
    w = words(text)
    if len(w) < 25:
        return 50.0, "too short to judge"
    per100 = 100 / len(w)
    contractions = len(CONTRACTIONS.findall(text)) * per100
    person = len(PRONOUNS.findall(text)) * per100
    tells = 0
    names = []
    for s in lex["structures"]:
        try:
            n = len(re.compile(s["regex"], re.MULTILINE).findall(text))
        except re.error:
            continue
        if n:
            tells += n
            names.append(s["id"])
    bullets = [len(b.split()) for b in re.findall(r"(?m)^\s*[-*•]\s+(.+)$", text)]
    uniform = (len(bullets) >= 3 and statistics.pstdev(bullets) < 1.6)
    score = (scale(contractions, human=3.0, machine=0.0) * 0.35
             + scale(person, human=8.0, machine=1.0) * 0.35
             + clamp(100 - tells * 22) * 0.30)
    if uniform:
        score -= 12
        names.append("uniform-bullets")
    detail = (f"{contractions:.1f} contractions, {person:.1f} personal pronouns "
              f"per 100 words, {tells} structural tell(s)")
    if names:
        detail += " [" + ", ".join(names[:4]) + "]"
    return clamp(score), detail


CHECKS = ["BURSTINESS", "SPECIFICITY", "SLOP DENSITY", "FINGERPRINT", "VOICE"]


def run(text, lex):
    results = {}
    results["BURSTINESS"] = check_burstiness(text)
    results["SPECIFICITY"] = check_specificity(text)
    results["SLOP DENSITY"] = check_slop(text, lex)
    results["FINGERPRINT"] = check_fingerprint(text)
    results["VOICE"] = check_voice(text, lex)
    scores = [results[c][0] for c in CHECKS]
    # The weakest check drags the verdict: a detector only needs one signal.
    overall = statistics.mean(scores) * 0.6 + min(scores) * 0.4
    verdict = "PASS" if overall >= 70 and min(scores) >= 55 else (
        "REVIEW" if overall >= 50 else "FLAGGED")
    return results, overall, verdict


# ---------------------------------------------------------------------------
# Spanish
#
# Added beside the English panel, which is untouched, and used when the draft is Spanish
# (detected, or --lang es). Same five checks, same 0-100 scale, same verdict logic. What changes:
#   * words: accented letters are letters (the English word regex would cut "canción" in two).
#   * SPECIFICITY: capitalised words after ¿ or ¡ are sentence starts, not names. English
#     gets months and weekdays "for free" because it capitalises them, Spanish does not, so they
#     are counted by name here to keep the two measures comparable.
#   * SLOP DENSITY: slop.es.json, matched without regard to accents.
#   * FINGERPRINT: a dash that opens a line is Spanish dialogue punctuation, not a tell.
#   * VOICE: Spanish has no contractions, so that third of the English score is dropped and the
#     rest re-weighted. Person is counted from pronouns and clitics (me, te, tu, nos...) because
#     Spanish drops the subject pronoun and carries the person in the verb ending.
# The thresholds are the English ones, carried over, not tuned on real Spanish text, and the
# word list is short. Treat the scores as a rough signal: they flag the obvious and can move the
# wrong way on a small edit.
# ---------------------------------------------------------------------------

LEX_ES = os.path.join(HERE, "slop.es.json")


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


ES_VOWELS = {"a": "aá", "e": "eé", "i": "ií", "o": "oó", "u": "uúü"}


def es_pattern(find):
    """Regex source for a lexicon string: any vowel matches with or without its accent."""
    out = []
    for ch in strip_accents(find):
        if ch in ES_VOWELS:
            out.append("[" + ES_VOWELS[ch] + "]")
        elif ch.isspace():
            out.append(r"\s+")
        else:
            out.append(re.escape(ch))
    return "".join(out)


def es_entry_pattern(entry):
    """One compiled pattern for an entry and all of its `forms`, longest form first."""
    forms = sorted({entry["find"], *entry.get("forms", [])}, key=len, reverse=True)
    return re.compile(r"(?<!\w)(?:" + "|".join(es_pattern(f) for f in forms) + r")(?!\w)", re.IGNORECASE)


def load_lexicon_es(path=LEX_ES):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


ES_WORD_RE = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ']+")
ES_NUMBERS = re.compile(r"\b\d[\d,.]*%?\b|[$€]\s?\d")
ES_PROPER = re.compile(r"(?<![.!?]\s)(?<![¿¡])(?<!^)\b[A-ZÁÉÍÓÚÑ][a-záéíóúüñ]{2,}\b", re.MULTILINE)
ES_CALENDAR = re.compile(r"\b(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre"
                         r"|noviembre|diciembre|lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)\b",
                         re.IGNORECASE)
ES_PRONOUNS = re.compile(r"\b(?:yo|me|mi|mis|conmigo|nosotros|nosotras|nos|nuestro|nuestra|nuestros|nuestras"
                         r"|tu|tus|te|ti|contigo|vos|usted|ustedes|vosotros|vosotras|os|vuestro|vuestra"
                         r"|vuestros|vuestras)\b")      # run on strip_accents(text)


def es_words(text):
    return ES_WORD_RE.findall(text)


def es_check_specificity(text):
    """Numbers, names and concrete nouns. Slop is abstract."""
    w = es_words(text)
    if len(w) < 25:
        return 50.0, "too short to judge"
    per100 = 100 / len(w)
    hits = (len(ES_NUMBERS.findall(text)) + len(set(ES_PROPER.findall(text)))
            + len({m.lower() for m in ES_CALENDAR.findall(text)}))
    density = hits * per100
    score = scale(density, human=6.0, machine=0.5)
    return score, f"{hits} concrete markers, {density:.1f} per 100 words (want 4+)"


def es_check_slop(text, lex):
    """Stock vocabulary density against the Spanish lexicon."""
    w = es_words(text)
    if not w:
        return 50.0, "empty"
    hits, found = 0, []
    for entry in lex["words"] + lex["phrases"]:
        n = len(es_entry_pattern(entry).findall(text))
        if n:
            hits += n
            found.append(entry["find"])
    density = hits * 100 / len(w)
    score = scale(density, human=0.0, machine=4.0)
    detail = f"{hits} stock terms, {density:.1f} per 100 words"
    if found:
        detail += " (" + ", ".join(sorted(found)[:4]) + (", ..." if len(found) > 4 else "") + ")"
    return score, detail


def es_check_fingerprint(text):
    """Characters a phone keyboard does not produce. A dash opening a line is dialogue, not a tell."""
    invisible = sum(1 for c in text if unicodedata.category(c) == "Cf")
    em = text.count("—") - len(re.findall(r"(?m)^[ \t]*—", text))
    curly = sum(text.count(c) for c in "‘’“”")
    ellip = text.count("…")
    nbsp = sum(text.count(c) for c in "\u00a0\u202f\u2009")
    total = invisible * 4 + em * 2 + curly + ellip + nbsp
    per1k = total * 1000 / max(len(text), 1)
    score = scale(per1k, human=0.0, machine=12.0)
    detail = (f"{invisible} invisible, {em} em dash, {curly} curly quote, "
              f"{ellip} ellipsis, {nbsp} hard space")
    return score, detail


def es_check_voice(text, lex):
    """Person and the shapes models default to. No contractions in Spanish, so no third term."""
    w = es_words(text)
    if len(w) < 25:
        return 50.0, "too short to judge"
    per100 = 100 / len(w)
    person = len(ES_PRONOUNS.findall(strip_accents(text))) * per100
    tells = 0
    names = []
    for s in lex["structures"]:
        try:
            n = len(re.compile(s["regex"], re.MULTILINE).findall(text))
        except re.error:
            continue
        if n:
            tells += n
            names.append(s["id"])
    bullets = [len(b.split()) for b in re.findall(r"(?m)^\s*[-*•]\s+(.+)$", text)]
    uniform = (len(bullets) >= 3 and statistics.pstdev(bullets) < 1.6)
    score = scale(person, human=8.0, machine=1.0) * 0.6 + clamp(100 - tells * 22) * 0.4
    if uniform:
        score -= 12
        names.append("uniform-bullets")
    detail = f"{person:.1f} personal pronouns per 100 words, {tells} structural tell(s)"
    if names:
        detail += " [" + ", ".join(names[:4]) + "]"
    return clamp(score), detail


def run_es(text, lex):
    results = {}
    results["BURSTINESS"] = check_burstiness(text)
    results["SPECIFICITY"] = es_check_specificity(text)
    results["SLOP DENSITY"] = es_check_slop(text, lex)
    results["FINGERPRINT"] = es_check_fingerprint(text)
    results["VOICE"] = es_check_voice(text, lex)
    scores = [results[c][0] for c in CHECKS]
    overall = statistics.mean(scores) * 0.6 + min(scores) * 0.4
    verdict = "PASS" if overall >= 70 and min(scores) >= 55 else (
        "REVIEW" if overall >= 50 else "FLAGGED")
    return results, overall, verdict


def bar(score, width=24):
    filled = round(score / 100 * width)
    return "#" * filled + "." * (width - filled)


def render(results, overall, verdict, label=None, out=sys.stdout):
    title = "AI DETECTION PANEL" + (f"  -  {label}" if label else "")
    print("\n" + title, file=out)
    print("=" * max(len(title), 62), file=out)
    for name in CHECKS:
        score, detail = results[name]
        print(f"  {name:<13} {bar(score)} {score:5.1f}", file=out)
        print(f"  {'':<13} {detail}", file=out)
    print("-" * 62, file=out)
    print(f"  {'HUMAN SCORE':<13} {bar(overall)} {overall:5.1f}   {verdict}", file=out)
    if verdict != "PASS":
        weakest = min(CHECKS, key=lambda c: results[c][0])
        print(f"\n  Weakest signal: {weakest}. Fix that first.", file=out)
    print("", file=out)


def main():
    ap = argparse.ArgumentParser(description="Score how machine-written a draft looks.")
    ap.add_argument("input", nargs="?", default="-", help="file, or - for stdin")
    ap.add_argument("compare", nargs="?", help="second file, to show before/after")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--lexicon", default=LEX, help="path to slop.json (slop.es.json for Spanish)")
    ap.add_argument("--lang", choices=["auto", "en", "es"], default="auto",
                    help="language of the draft (default: detect it for each file)")
    args = ap.parse_args()

    lex = json.load(open(args.lexicon, encoding="utf-8"))
    read = lambda p: sys.stdin.read() if p == "-" else open(p, encoding="utf-8").read()

    targets = [(args.input, read(args.input))]
    if args.compare:
        targets.append((args.compare, read(args.compare)))

    langs = [args.lang if args.lang != "auto" else detect_lang(text) for _, text in targets]
    lex_es = None
    if "es" in langs:
        print(f"language: Spanish ({'forced' if args.lang != 'auto' else 'detected'}). The Spanish word "
              "list and thresholds are a first version, not tuned on real Spanish text.", file=sys.stderr)
        lex_es = load_lexicon_es(LEX_ES if args.lexicon == LEX else args.lexicon)
    analyse = lambda text, lang: run_es(text, lex_es) if lang == "es" else run(text, lex)

    payload = []
    for (name, text), lang in zip(targets, langs):
        results, overall, verdict = analyse(text, lang)
        payload.append({
            "source": name,
            "checks": {k: {"score": round(v[0], 1), "detail": v[1]} for k, v in results.items()},
            "human_score": round(overall, 1),
            "verdict": verdict,
        })
        if lang == "es":
            payload[-1]["lang"] = "es"

    if args.json:
        print(json.dumps(payload if args.compare else payload[0], indent=2, ensure_ascii="es" not in langs))
        return

    for (name, text), lang, p in zip(targets, langs, payload):
        results, overall, verdict = analyse(text, lang)
        render(results, overall, verdict, label=os.path.basename(name) if args.compare else None)
    if args.compare:
        a, b = payload
        delta = b["human_score"] - a["human_score"]
        print(f"  {a['human_score']:.1f} {a['verdict']}  ->  "
              f"{b['human_score']:.1f} {b['verdict']}   ({delta:+.1f})\n")

    sys.exit(0 if payload[-1]["verdict"] == "PASS" else 1)


if __name__ == "__main__":
    main()
