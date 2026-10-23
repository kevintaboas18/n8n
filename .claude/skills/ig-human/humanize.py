#!/usr/bin/env python3
"""
humanize.py - strip the machine fingerprint out of a draft.

Three passes, in this order:

  1. INVISIBLE   delete or normalise the characters a human keyboard never
                 produces: zero-width joiners, word joiners, soft hyphens,
                 BOMs, Unicode tag characters, non-breaking and narrow spaces.
                 These survive copy-paste and are the most mechanical tell in
                 any generated text.
  2. TYPOGRAPHIC em dash -> comma, en dash -> hyphen, curly quotes -> straight,
                 ellipsis -> three dots, bullet -> hyphen.
  3. LEXICAL     replace the slop lexicon in slop.json with plain words,
                 preserving capitalisation and leaving URLs untouched.

Structural tells (rule-of-three, "not just X, it's Y", hashtag walls) are
REPORTED, never auto-rewritten - rewriting a sentence's shape needs judgement,
so that is the model's job, not a regex's.

Usage
  python3 humanize.py draft.txt
  python3 humanize.py draft.txt --report
  pbpaste | python3 humanize.py - --report
  python3 humanize.py draft.txt --json
  python3 humanize.py draft.txt -o clean.txt
  python3 humanize.py borrador.txt --lang es      # Spanish is detected on its own; this forces it
"""

import argparse
import json
import os
import re
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
LEX = os.path.join(HERE, "slop.json")

URL_RE = re.compile(r"https?://\S+|www\.\S+|\S+@\S+\.\S+")
SENT_RE = re.compile(r"[^.!?\n]+[.!?]*")


def load_lexicon(path=LEX):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _cp(spec):
    """'U+200B' -> '\\u200b';  'U+E0000-U+E007F' -> (start, end)."""
    if "-" in spec:
        a, b = spec.split("-")
        return (int(a[2:], 16), int(b[2:], 16))
    return int(spec[2:], 16)


def protect_urls(text):
    """Swap URLs for placeholders so no pass rewrites inside a link."""
    found = []

    def stash(m):
        found.append(m.group(0))
        return f"\x00URL{len(found) - 1}\x00"

    return URL_RE.sub(stash, text), found


def restore_urls(text, found):
    for i, url in enumerate(found):
        text = text.replace(f"\x00URL{i}\x00", url)
    return text


def pass_invisible(text, lex):
    """Delete or space-normalise invisible characters. Returns (text, hits)."""
    hits = []
    for entry in lex["invisible"]:
        cp = _cp(entry["cp"])
        if isinstance(cp, tuple):
            pattern = "[" + re.escape(chr(cp[0])) + "-" + re.escape(chr(cp[1])) + "]"
        else:
            pattern = re.escape(chr(cp))
        n = len(re.findall(pattern, text))
        if n:
            hits.append({"name": entry["cp"] + " " + entry["name"], "count": n,
                         "action": entry["action"]})
            text = re.sub(pattern, "" if entry["action"] == "delete" else " ", text)
    # Any remaining Cf (format) character is invisible by definition.
    stray = [c for c in text if unicodedata.category(c) == "Cf"]
    if stray:
        hits.append({"name": "other invisible format chars", "count": len(stray),
                     "action": "delete"})
        text = "".join(c for c in text if unicodedata.category(c) != "Cf")
    return text, hits


def pass_typographic(text, lex):
    hits = []
    for entry in lex["typographic"]:
        ch = entry["from"]
        n = text.count(ch)
        if not n:
            continue
        hits.append({"name": f"{ch} {entry['name']}", "count": n, "to": entry["to"].strip() or "(space)"})
        if ch == "—":
            # " word — word " and "word—word" both collapse to a comma + space.
            text = re.sub(r"\s*—\s*", ", ", text)
        elif ch == "–":
            text = re.sub(r"\s*–\s*(?=\d)", "-", text)      # 5–10  -> 5-10
            text = re.sub(r"\s+–\s+", ", ", text)            # used as em dash
            text = text.replace("–", "-")
        else:
            text = text.replace(ch, entry["to"])
    # A comma inserted before existing punctuation reads wrong.
    text = re.sub(r",\s*([,.;:!?])", r"\1", text)
    text = re.sub(r",\s*\n", "\n", text)
    return text, hits


def _match_case(src, repl):
    if not repl:
        return repl
    if src.isupper() and len(src) > 1:
        return repl.upper()
    if src[0].isupper():
        return repl[0].upper() + repl[1:]
    return repl


def pass_lexical(text, lex):
    """Replace slop words and phrases. Longest first so phrases win."""
    hits = []
    entries = sorted(lex["phrases"] + lex["words"],
                     key=lambda e: len(e["find"]), reverse=True)
    for entry in entries:
        find = entry["find"]
        pattern = re.compile(r"\b" + re.escape(find).replace(r"\ ", r"\s+") + r"\b",
                             re.IGNORECASE)
        found = pattern.findall(text)
        if not found:
            continue
        hits.append({"find": find, "replace": entry["replace"] or "(deleted)",
                     "count": len(found), "family": entry["family"]})
        text = pattern.sub(lambda m: _match_case(m.group(0), entry["replace"]), text)
    # Clean up after deletions. Deleting a whole clause leaves orphaned
    # punctuation behind ("system. ." or a line that now opens on a comma),
    # and that reads worse than the slop did.
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"(?m)^[ \t]*(?:[,.;:]+[ \t]*)+", "", text)
    text = re.sub(r"(?m)^[ \t](?=\S)", "", text)       # one space left by a deletion.
                                                      # Deeper indents are deliberate.
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r",\s*([,.;:!?])", r"\1", text)      # an em dash became a comma,
                                                      # then the clause after it went
    text = text.replace("...", "\x00ELL\x00")          # protect real ellipses
    text = re.sub(r"\.\s*\.+", ".", text)
    text = re.sub(r"([!?])\s*\.", r"\1", text)
    text = text.replace("\x00ELL\x00", "...")
    text = re.sub(r"(?m)^[ \t]+$", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    # An em dash that became a comma, followed by a sentence connective, leaves
    # a splice ("is important, also, it's proof"). Promote it to a full stop.
    text = re.sub(r",\s*(also|so|still|basically|in the end)\s*,\s*",
                  lambda m: ". " + m.group(1)[0].upper() + m.group(1)[1:] + ", ", text)
    return text, hits


def scan_structures(text, lex):
    flags = []
    for s in lex["structures"]:
        try:
            pattern = re.compile(s["regex"], re.MULTILINE)
        except re.error:
            continue
        found = pattern.findall(text)
        if found:
            flags.append({"name": s["name"], "count": len(found), "fix": s["fix"]})
    # Sentence-length uniformity is structural too.
    lens = [len(s.split()) for s in SENT_RE.findall(text) if len(s.split()) > 2]
    if len(lens) >= 4:
        mean = sum(lens) / len(lens)
        var = sum((n - mean) ** 2 for n in lens) / len(lens)
        cv = (var ** 0.5) / mean if mean else 0
        if cv < 0.35:
            flags.append({
                "name": f"Uniform sentence length (variation {cv:.2f})",
                "count": len(lens),
                "fix": "Break one sentence in half. Let another run long. Machines write even.",
            })
    return flags


def restore_capitals(original, text):
    """Deleting an opener leaves the next word lower case.

    Only fix it for writers who capitalise their sentences in the first place:
    a deliberately lower-case voice is a style, not an artefact, and shouting
    over it would be exactly the kind of thing this script exists to stop.
    """
    starts = re.findall(r"(?:^|[.!?]\s+|\n)\s*([A-Za-z])", original)
    if not starts or sum(1 for c in starts if c.isupper()) * 2 < len(starts):
        return text
    return re.sub(r"(?:^|(?<=[.!?] )|(?<=[.!?]\n)|(?<=\n))\s*([a-z])",
                  lambda m: m.group(0)[:-1] + m.group(1).upper(), text)


def humanize(text, lex):
    raw_for_case = text
    text, urls = protect_urls(text)
    text, inv = pass_invisible(text, lex)
    text, typo = pass_typographic(text, lex)
    text, lexi = pass_lexical(text, lex)
    text = restore_capitals(raw_for_case, text)
    text = restore_urls(text, urls)
    return text.strip() + "\n", {
        "invisible": inv,
        "typographic": typo,
        "lexical": lexi,
        "structures": scan_structures(text, lex),
    }


# ---------------------------------------------------------------------------
# Spanish
#
# Added beside the English code, which is untouched, and used when the draft is Spanish
# (detected, or --lang es). Invisible characters are language-independent, so that pass
# is shared. What changes:
#   * typography: a dash that opens a line is Spanish dialogue punctuation (la raya), not a
#     machine tell, so it is left alone. Guillemets and the inverted marks are never touched.
#   * lexicon: slop.es.json. Matching ignores accents (people drop them) but keeps the
#     n-tilde. Spanish verbs and adjectives change with person, gender and number, so a blind
#     swap writes broken grammar: those entries are REPORTED, not changed. Only stock openers
#     and closers are deleted, and only invariable connectives are swapped.
# A first version, not tuned on a corpus of real Spanish captions.
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


def load_lexicon_es(path=LEX_ES, base=LEX):
    lex = load_lexicon(path)
    common = load_lexicon(base)
    for key in ("invisible", "typographic"):          # language-independent, kept in slop.json
        lex.setdefault(key, common[key])
    return lex


def pass_typographic_es(text, lex):
    """Like pass_typographic, but a dash that opens a line (dialogue) is left alone."""
    text = re.sub(r"(?m)^([ \t]*)—", "\\1\x00RAYA\x00", text)
    text, hits = pass_typographic(text, lex)
    return text.replace("\x00RAYA\x00", "—"), hits


DELETED = "\x01"          # stands where a phrase was deleted, so only those spots get tidied
ES_EMOJI = "[\U0001F300-\U0001FAFF\u2600-\u27BF\ufe0f]"


def resolve_deleted(text):
    """Tidy the punctuation around deleted phrases without touching punctuation that was always there."""
    d = DELETED
    text = re.sub(d + r"(?:[ \t]*" + d + ")+", d, text)
    # a sentence that was nothing but the deleted phrase goes, with its closing mark
    text = re.sub(r"(?m)^([ \t]*)" + d + r"[ \t]*[.!?]+", r"\1", text)
    text = re.sub(r"(?<=[.!?¡¿])[ \t]+" + d + r"[ \t]*[.!?]+", "", text)
    text = re.sub(r"(?<=" + ES_EMOJI + r")[ \t]*" + d + r"[ \t]*[.!?]+", "", text)
    # a deleted opener leaves the sentence starting on the next word
    text = re.sub(r"(?m)^([ \t]*)" + d + r"[ \t]*", r"\1", text)
    text = re.sub(r"(?<=[.!?¡¿] )" + d + r"[ \t]*", "", text)
    # mid-sentence: no space before a closing mark, one space otherwise
    text = re.sub(r"[ \t]*" + d + r"[ \t]*(?=[,.;:!?)»\"”])", "", text)
    return re.sub(r"[ \t]*" + d + r"[ \t]*", " ", text)


def pass_lexical_es(text, lex):
    """Spanish counterpart of pass_lexical. Returns (text, changed, reported_only)."""
    hits, reported = [], []
    entries = sorted(lex["phrases"] + lex["words"],
                     key=lambda e: max(len(f) for f in [e["find"], *e.get("forms", [])]), reverse=True)
    for entry in entries:
        pattern = es_entry_pattern(entry)
        n = len(pattern.findall(text))
        if not n:
            continue
        if entry["replace"] is None:
            reported.append({"find": entry["find"], "count": n, "family": entry["family"]})
            continue
        hits.append({"find": entry["find"], "replace": entry["replace"] or "(deleted)",
                     "count": n, "family": entry["family"]})
        if entry["replace"]:
            text = pattern.sub(lambda m: _match_case(m.group(0), entry["replace"]), text)
        else:                      # a deleted phrase takes its own comma or colon with it, and the
            body = pattern.pattern  # comma before it when it sat between two commas
            text = re.sub(r",[ \t]*" + body + r"[ \t]*,", DELETED, text, flags=re.IGNORECASE)
            text = re.sub(body + r"(?:[ \t]*[,:;])?", DELETED, text, flags=re.IGNORECASE)
    text = resolve_deleted(text)
    # Same clean-up as the English pass, plus the inverted marks a deleted clause can orphan.
    # (The English "splice" rule is left out: ", también," is ordinary Spanish.)
    text = re.sub(r"¡\s*!|¿\s*\?", "", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"(?m)^[ \t]*(?:[,.;:]+[ \t]*)+", "", text)
    text = re.sub(r"(?m)^[ \t](?=\S)", "", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r",\s*([,.;:!?])", r"\1", text)
    text = text.replace("...", "\x00ELL\x00")
    text = re.sub(r"\.\s*\.+", ".", text)
    text = re.sub(r"([!?])\s*\.", r"\1", text)
    text = text.replace("\x00ELL\x00", "...")
    text = re.sub(r"(?m)^[ \t]+$", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text, hits, reported


def restore_capitals_es(original, text):
    """As restore_capitals, for Spanish: accented letters, and a sentence may open on ¿ or ¡."""
    starts = re.findall(r"(?:^|[.!?]\s+|\n)\s*[¿¡]?([^\W\d_])", original)
    if not starts or sum(1 for c in starts if c.isupper()) * 2 < len(starts):
        return text
    return re.sub(r"(?:^|(?<=[.!?] )|(?<=[.!?]\n)|(?<=\n))(\s*[¿¡]?)([a-záéíóúüñ])",
                  lambda m: m.group(1) + m.group(2).upper(), text)


def humanize_es(text, lex):
    raw_for_case = text
    text, urls = protect_urls(text)
    text, inv = pass_invisible(text, lex)
    text, typo = pass_typographic_es(text, lex)
    text, lexi, reported = pass_lexical_es(text, lex)
    text = restore_capitals_es(raw_for_case, text)
    text = restore_urls(text, urls)
    return text.strip() + "\n", {
        "invisible": inv,
        "typographic": typo,
        "lexical": lexi,
        "structures": scan_structures(text, lex),
        "reported": reported,
    }


def render_report(report, out=sys.stderr):
    def head(title):
        print(f"\n{title}\n" + "-" * len(title), file=out)

    total = sum(h["count"] for h in report["invisible"]) \
        + sum(h["count"] for h in report["typographic"]) \
        + sum(h["count"] for h in report["lexical"])

    head("HUMANIZE REPORT")
    print(f"{total} machine artefacts removed, "
          f"{len(report['structures'])} structural tells flagged for rewrite", file=out)
    if report.get("reported"):
        print(f"{sum(h['count'] for h in report['reported'])} stock terms reported but not changed "
              "(Spanish: they change with person, gender and number)", file=out)

    if report["invisible"]:
        head("1. INVISIBLE CHARACTERS")
        for h in report["invisible"]:
            print(f"  {h['count']:>3}x  {h['name']}  -> {h['action']}", file=out)
    if report["typographic"]:
        head("2. TYPOGRAPHY")
        for h in report["typographic"]:
            print(f"  {h['count']:>3}x  {h['name']}  -> {h['to']}", file=out)
    if report["lexical"]:
        head("3. SLOP LEXICON")
        for h in report["lexical"]:
            print(f"  {h['count']:>3}x  {h['find']}  -> {h['replace']}   [{h['family']}]", file=out)
    if report.get("reported"):
        head("3b. STOCK TERMS REPORTED, NOT CHANGED  (rewrite these yourself)")
        for h in report["reported"]:
            print(f"  {h['count']:>3}x  {h['find']}   [{h['family']}]", file=out)
    if report["structures"]:
        head("4. STRUCTURAL TELLS  (not auto-fixed - rewrite these yourself)")
        for h in report["structures"]:
            print(f"  {h['count']:>3}x  {h['name']}\n        {h['fix']}", file=out)
    if not any(report.values()):
        head("CLEAN")
        print("  Nothing to strip.", file=out)
    print("", file=out)


def main():
    ap = argparse.ArgumentParser(description="Strip the machine fingerprint out of a draft.")
    ap.add_argument("input", nargs="?", default="-", help="file, or - for stdin")
    ap.add_argument("-o", "--out", help="write cleaned text here instead of stdout")
    ap.add_argument("--report", action="store_true", help="print what changed, to stderr")
    ap.add_argument("--json", action="store_true", help="emit {text, report} as JSON")
    ap.add_argument("--lexicon", default=LEX, help="path to slop.json (slop.es.json for Spanish)")
    ap.add_argument("--lang", choices=["auto", "en", "es"], default="auto",
                    help="language of the draft (default: detect it)")
    args = ap.parse_args()

    raw = sys.stdin.read() if args.input == "-" else open(args.input, encoding="utf-8").read()
    lang = args.lang if args.lang != "auto" else detect_lang(raw)
    if lang == "es":
        print(f"language: Spanish ({'forced' if args.lang != 'auto' else 'detected'})", file=sys.stderr)
        lex = load_lexicon_es(LEX_ES if args.lexicon == LEX else args.lexicon)
        clean, report = humanize_es(raw, lex)
    else:
        lex = load_lexicon(args.lexicon)
        clean, report = humanize(raw, lex)

    if args.json:
        payload = {"text": clean, "report": report}
        if lang == "es":
            payload = {"lang": "es", **payload}
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(clean)
        print(f"wrote {args.out}", file=sys.stderr)
    else:
        sys.stdout.write(clean)
    if args.report:
        render_report(report)


if __name__ == "__main__":
    main()
