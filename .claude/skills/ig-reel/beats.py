#!/usr/bin/env python3
"""
beats.py - turn a Reel script into a timed beat sheet before you record it.

Estimates how long each line takes to say, stacks them into timecodes, and
flags the four things that kill a Reel in the edit: a hook that runs past the
three-second mark, a beat long enough for the viewer to leave, a run of lines
with nothing concrete in them, and a total length that does not match what you
said you were making.

The timings are an estimate from word count at a words-per-minute rate. They
are close enough to plan an edit and not a substitute for recording it. Set
your own rate with --wpm once you have timed yourself reading a script out
loud: most people land between 150 and 200, and the default here is 165.

Usage
  python3 beats.py script.txt
  python3 beats.py script.txt --target 30
  python3 beats.py script.txt --wpm 185 --target 45
  pbpaste | python3 beats.py -
  python3 beats.py script.txt --json
"""

import argparse
import json
import re
import sys
import unicodedata

WORD_RE = re.compile(r"[A-Za-z0-9$%'’-]+")
SENT_RE = re.compile(r"[^.!?]+[.!?]*")
CONCRETE_RE = re.compile(r"\$\s?\d|\b\d[\d,.]*\b|(?<!^)\b[A-Z][a-z]{2,}\b", re.MULTILINE)
STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "of", "to", "in", "on", "for",
    "with", "that", "this", "it", "is", "are", "was", "were", "be", "been",
    "you", "your", "i", "my", "me", "we", "our", "they", "them", "he", "she",
    "so", "just", "not", "no", "do", "did", "does", "have", "has", "had",
    "will", "can", "at", "as", "by", "from", "out", "up", "off", "one", "all",
}

HOOK_WINDOW = 3.0        # seconds. Past this, the thumb has already decided.
MAX_BEAT = 4.0           # seconds on one idea with no change on screen.
ABSTRACT_RUN = 3         # beats in a row with nothing checkable in them.


# Spanish, added next to the English code, which is untouched. The timing maths is the same: it
# counts words at a words-per-minute rate. What differs is what counts as a word (accents), what
# counts as concrete, and which words are too common to count as an echo of the hook.
def strip_accents(text):
    """Lower-case and drop accents, keeping the n-tilde."""
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
ES_CONCRETE_RE = re.compile(
    r"\$\s?\d|€\s?\d|\b\d[\d,.]*\b|(?<!^)(?<![¿¡])(?<![.!?]\s)\b[A-ZÁÉÍÓÚÑ][a-záéíóúüñ]{2,}\b", re.MULTILINE)
ES_STOPWORDS = {
    "el", "la", "los", "las", "un", "una", "unos", "unas", "y", "o", "u", "e", "pero", "si", "de", "del", "a",
    "al", "en", "con", "por", "para", "que", "es", "son", "era", "fue", "ser", "esta", "este", "eso", "esto",
    "estos", "estas", "tu", "tus", "te", "ti", "yo", "mi", "mis", "me", "nos", "nuestro", "ellos", "ellas",
    "lo", "le", "les", "se", "no", "ya", "muy", "mas", "todo", "todos", "como", "cuando", "donde", "tambien",
    "solo", "sin", "sobre", "entre", "hay", "he", "has", "ha", "han", "va", "voy", "vas", "vamos", "fui",
    "tengo", "tiene", "tienes", "quiero", "puedo", "asi", "aqui", "ahora", "hoy", "cada", "otra", "otro",
    "mismo", "misma", "tan", "tanto", "menos", "ni", "sino",
}


def words(text, lang="en"):
    # "$18,000" is one word when it is spoken, so it is one word here too.
    if lang == "es":                         # 18.000 and 1,5 are each one spoken number
        return ES_WORD_RE.findall(re.sub(r"(?<=\d)[.,](?=\d)", "", text))
    return WORD_RE.findall(re.sub(r"(?<=\d),(?=\d)", "", text))


def pretty(token, sep=","):
    """Put the thousands separator back for display."""
    return re.sub(r"(\d)(?=(\d{3})+$)", r"\1" + sep, token)


def tc(seconds):
    m, s = divmod(seconds, 60)
    return f"{int(m)}:{s:04.1f}"


def split_beats(raw, wps, lang="en"):
    """One line is one beat, unless a line is too long to be one."""
    beats = []
    for line in [l.strip() for l in raw.splitlines()]:
        if not line:
            continue
        if len(words(line, lang)) / wps <= MAX_BEAT * 1.5:
            beats.append(line)
            continue
        # Long paragraph: break it at sentence ends so the timings mean
        # something, and let the report say it was split.
        parts = [p.strip() for p in SENT_RE.findall(line) if p.strip()]
        buf = ""
        for part in parts:
            candidate = (buf + " " + part).strip()
            if buf and len(words(candidate, lang)) / wps > MAX_BEAT:
                beats.append(buf)
                buf = part
            else:
                buf = candidate
        if buf:
            beats.append(buf)
    return beats


def analyse(raw, wpm=165, target=None, lang="en"):
    wps = wpm / 60.0
    beats = split_beats(raw, wps, lang)
    if not beats:
        return None
    concrete_re = ES_CONCRETE_RE if lang == "es" else CONCRETE_RE

    rows, clock = [], 0.0
    for i, text in enumerate(beats):
        n = len(words(text, lang))
        dur = n / wps
        rows.append({
            "n": i + 1,
            "start": round(clock, 2),
            "dur": round(dur, 2),
            "words": n,
            "text": text,
            "concrete": len(concrete_re.findall(text)),
            "label": "",
            "flags": [],
        })
        clock += dur
    total = clock

    # Label the structural positions a Reel is actually built around.
    for r in rows:
        if r["n"] == 1 or r["start"] + r["dur"] <= HOOK_WINDOW:
            r["label"] = "HOOK"
    rows[-1]["label"] = "CTA" if rows[-1]["label"] != "HOOK" else "HOOK/CTA"
    half = total / 2
    for r in rows:
        if not r["label"] and r["start"] <= half < r["start"] + r["dur"]:
            r["label"] = "MID"

    notes = []
    if rows[0]["dur"] > HOOK_WINDOW:
        rows[0]["flags"].append(f"hook runs {rows[0]['dur']:.1f}s, past the {HOOK_WINDOW:.0f}s mark")
        notes.append(f"Beat 1 takes {rows[0]['dur']:.1f}s to say. Cut it to "
                     f"{int(HOOK_WINDOW * wps)} words or fewer, or the hook lands after "
                     "the decision has been made.")
    if rows[0]["concrete"] == 0:
        notes.append("Beat 1 has no number and no name in it. Hooks without something "
                     "checkable are the ones that get scrolled.")

    for r in rows:
        if r["dur"] > MAX_BEAT:
            r["flags"].append(f"{r['dur']:.1f}s on one beat")
    long_beats = [r["n"] for r in rows if r["dur"] > MAX_BEAT]
    if long_beats:
        notes.append(f"Beat(s) {', '.join(map(str, long_beats))} run past {MAX_BEAT:.0f}s. "
                     "Either split the line or change what is on screen inside it. "
                     "A static frame is where people leave.")

    run, start = 0, None
    for r in rows:
        if r["concrete"] == 0:
            run += 1
            start = start if start is not None else r["n"]
            if run == ABSTRACT_RUN:
                notes.append(f"Beats {start}-{r['n']} have nothing concrete in them. "
                             "Put a number, a name or a price in one of them.")
        else:
            run, start = 0, None

    # Does the last line hand you back to the first one?
    if lang == "es":
        shown = {strip_accents(w): w.lower() for w in words(rows[0]["text"], lang)
                 if strip_accents(w) not in ES_STOPWORDS}
        last = {strip_accents(w) for w in words(rows[-1]["text"], lang)}
        loop = sorted(pretty(shown[k], ".") for k in shown.keys() & last)
    else:
        first = {w.lower() for w in words(rows[0]["text"]) if w.lower() not in STOPWORDS}
        last = {w.lower() for w in words(rows[-1]["text"]) if w.lower() not in STOPWORDS}
        loop = sorted(pretty(w) for w in first & last)
    if loop:
        notes.append(f"Loops: the last beat repeats \"{', '.join(loop[:3])}\" from the hook. "
                     "Second watches are free reach.")
    else:
        notes.append("No loop. The last beat shares no word with the hook, so the video "
                     "ends flat. Echoing one word from beat 1 is the cheapest replay you get.")

    if target:
        delta = total - target
        if abs(delta) <= target * 0.1:
            notes.append(f"Length is on target ({total:.1f}s against {target}s).")
        elif delta > 0:
            notes.append(f"{delta:.1f}s over target. Cut about {int(delta * wps)} words.")
        else:
            notes.append(f"{-delta:.1f}s under target. Either add {int(-delta * wps)} words "
                         "or shoot it short. Short is usually right.")

    return {
        "wpm": wpm, "target": target,
        "total_seconds": round(total, 2),
        "total_words": sum(r["words"] for r in rows),
        "beats": rows,
        "notes": notes,
    }


def render(a, out=sys.stdout):
    head = (f"BEAT SHEET  ·  {a['total_words']} words  ·  ~{a['total_seconds']:.1f}s "
            f"at {a['wpm']} wpm" + (f"  ·  target {a['target']}s" if a["target"] else ""))
    print("\n" + head, file=out)
    print("=" * max(len(head), 72), file=out)
    for r in a["beats"]:
        label = f"{r['label']:<8}" if r["label"] else " " * 8
        print(f"  {tc(r['start'])}  {r['dur']:4.1f}s  {label}{r['text']}", file=out)
        for f in r["flags"]:
            print(f"  {'':>6}  {'':>5}  {'':<8}^ {f}", file=out)
    print("-" * max(len(head), 72), file=out)
    for n in a["notes"]:
        print(f"  - {n}", file=out)
    print("", file=out)


def main():
    ap = argparse.ArgumentParser(description="Time a Reel script into a beat sheet.")
    ap.add_argument("input", nargs="?", default="-", help="script file, or - for stdin")
    ap.add_argument("--wpm", type=float, default=165, help="speaking rate (default 165)")
    ap.add_argument("--target", type=float, help="target length in seconds")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--lang", choices=["auto", "en", "es"], default="auto",
                    help="language of the script (default: detect it)")
    args = ap.parse_args()

    raw = sys.stdin.read() if args.input == "-" else open(args.input, encoding="utf-8").read()
    lang = args.lang if args.lang != "auto" else detect_lang(raw)
    if lang == "es":
        print(f"language: Spanish ({'forced' if args.lang != 'auto' else 'detected'})", file=sys.stderr)
    a = analyse(raw, wpm=args.wpm, target=args.target, lang=lang)
    if a and lang == "es":
        a["lang"] = "es"
    if not a:
        print("empty script", file=sys.stderr)
        sys.exit(2)
    if args.json:
        print(json.dumps(a, indent=2, ensure_ascii=False))
    else:
        render(a)
    sys.exit(0)


if __name__ == "__main__":
    main()
