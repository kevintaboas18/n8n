#!/usr/bin/env python3
"""
caption.py - lint an Instagram caption and show exactly what the feed shows
before the "... more".

Instagram gives a caption about 125 characters in the feed and hides the rest
behind a tap. Almost every caption that fails, fails there: the hook is in
sentence three, or the first line is a greeting, or the whole thing opens on a
hashtag. This prints the visible window as a box so you can read it the way a
scrolling stranger does, then checks the eight things that are worth checking.

The 125-character cut is an approximation. The real number moves with the
device, the font size and where your line breaks fall, which is exactly why
you want a margin rather than a caption engineered to end at 125. Change it
with --truncate if you want to test a tighter one.

Usage
  python3 caption.py caption.txt
  python3 caption.py caption.txt --keywords "proposal software,client contract"
  pbpaste | python3 caption.py -
  python3 caption.py caption.txt --json
"""

import argparse
import json
import re
import sys
import textwrap
import unicodedata

LIMIT = 2200             # Instagram's hard caption limit.
TRUNCATE = 125           # Roughly where the feed cuts to "... more".
HASHTAG_LIMIT = 5        # Instagram's cap per post or reel since 18 Dec 2025,
                         # down from 30. Announced by the @Creators account:
                         # "using fewer (up to 5) more targeted hashtags,
                         # rather than many generic ones, can improve both your
                         # content's performance and people's experience".

HASHTAG_RE = re.compile(r"(?:^|\s)(#[A-Za-z0-9_]+)")
MENTION_RE = re.compile(r"(?:^|\s)(@[A-Za-z0-9_.]+)")
LINK_RE = re.compile(r"https?://\S+|\bwww\.\S+|\b[a-z0-9-]+\.(?:com|co|io|net|org|ai|app)/\S*",
                     re.IGNORECASE)
EMOJI_RE = re.compile(r"[\U0001F300-\U0001FAFF☀-➿←-⇿️]")
CONCRETE_RE = re.compile(r"\$\s?\d|\b\d[\d,.]*\b|(?<!^)\b[A-Z][a-z]{2,}\b", re.MULTILINE)

ASKS = [
    (re.compile(r"(?i)\bcomment (?:the word |\")?[A-Z0-9]{2,}\b"), "comment a keyword"),
    (re.compile(r"(?i)\b(?:dm|message) me\b"), "DM me"),
    (re.compile(r"(?i)\bsave (?:this|it)\b"), "save this"),
    (re.compile(r"(?i)\bshare (?:this|it)\b"), "share this"),
    (re.compile(r"(?i)\bfollow (?:me|for)\b"), "follow"),
    (re.compile(r"(?i)\blink in (?:my )?bio\b"), "link in bio"),
    (re.compile(r"(?i)\b(?:swipe|tap) (?:through|left|right|for|to)\b"), "swipe or tap"),
    (re.compile(r"(?i)\btell me\b|\bwhat would you\b|\bwhich one\b"), "answer a question"),
]

FILLER_TAGS = {"#viral", "#fyp", "#explore", "#explorepage", "#foryou", "#foryoupage",
               "#trending", "#instagood", "#love", "#follow", "#like4like", "#reels",
               "#reelsinstagram", "#viralreels", "#instadaily"}


# ---------------------------------------------------------------------------
# Spanish, added next to the English code, which is untouched. The 125-character window, the
# 2,200 limit and the hashtag cap are the same in any language. What differs is what counts as
# a hashtag (ñ and accents), a call to action ("Comenta CONTRATO") and a filler tag. Patterns
# for asks are matched on accent-stripped lower-case text, so write them without accents.
# A first version, not tuned on a corpus of real Spanish captions.
# ---------------------------------------------------------------------------

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


ES_HASHTAG_RE = re.compile(r"(?:^|\s)(#[A-Za-z0-9_ÁÉÍÓÚÜÑáéíóúüñ]+)")
ES_LINK_RE = re.compile(r"https?://\S+|\bwww\.\S+|\b[a-z0-9-]+\.(?:com|co|io|net|org|ai|app|es|mx|ar|cl|pe|uy"
                        r"|ve|ec|bo|py|cr|pa|gt|hn|ni|sv|cu)/\S*", re.IGNORECASE)
ES_CONCRETE_RE = re.compile(
    r"\$\s?\d|€\s?\d|\b\d[\d,.]*\b|(?<!^)(?<![¿¡])(?<![.!?]\s)\b[A-ZÁÉÍÓÚÑ][a-záéíóúüñ]{2,}\b", re.MULTILINE)
ES_ASKS = [
    (re.compile(r"\bcomenta(?:r|me)?\s+(?:la palabra\s+|\")?[a-z0-9ñ]{2,}\b"), "comment a keyword"),
    (re.compile(r"\b(?:escribeme|mandame|enviame|hablame)\b[^.!?\n]{0,30}\b(?:dm|md|mensaje|privado|inbox)\b"
                r"|\bpor (?:dm|md|mensaje directo|privado)\b|\bdm me\b"), "DM me"),
    (re.compile(r"\bguarda(?:lo|la)?\s+(?:este|esta|esto|el|la)\b|\bguardal[oa]\b"), "save this"),
    (re.compile(r"\bcomparte(?:lo|la)?\s+(?:este|esta|esto)\b|\bcompartel[oa]\b"), "share this"),
    (re.compile(r"\bsigueme\b|\bsiguenos\b|\bsigue(?:me)? (?:para|si)\b"), "follow"),
    (re.compile(r"\b(?:enlace|link) (?:en|de) (?:mi |la |el )?(?:bio|biografia|perfil)\b"
                r"|\blink in (?:my )?bio\b"), "link in bio"),
    (re.compile(r"\bdesliza(?:lo)?\b|\barrastra (?:a la|hacia)\b|\btoca (?:el|la|aqui|para)\b"), "swipe or tap"),
    (re.compile(r"\bcuentame\b|\bdime\b|\bque harias\b|\bcual prefieres\b|\bque opinas\b|\bque piensas\b"),
     "answer a question"),
]
ES_FILLER_TAGS = {"#viral", "#parati", "#fyp", "#explorar", "#explore", "#explorepage", "#foryou",
                  "#foryoupage", "#trending", "#tendencia", "#tendencias", "#instagood", "#love", "#amor",
                  "#follow", "#sigueme", "#like4like", "#likeforlike", "#followforfollow", "#reels",
                  "#reelsinstagram", "#reelsvideo", "#instadaily", "#instagram", "#megusta", "#foto",
                  "#fotodeldia", "#viralreels"}


def visible_window(text, cut):
    """What the feed shows. Instagram cuts mid-word, so this does too."""
    flat = text.strip()
    return flat if len(flat) <= cut else flat[:cut]


def render_box(window, truncated, out=sys.stdout, width=52):
    print("\n  WHAT THE FEED SHOWS", file=out)
    print("  +" + "-" * (width + 2) + "+", file=out)
    lines = []
    for raw in window.split("\n"):
        lines.extend(textwrap.wrap(raw, width) or [""])
    for line in lines[:8]:
        print(f"  | {line:<{width}} |", file=out)
    tail = "... more" if truncated else "(whole caption fits)"
    print("  +" + "-" * (width + 2 - len(tail) - 2) + f" {tail} " + "+", file=out)


def analyse(text, cut=TRUNCATE, keywords=None, lang="en"):
    es = lang == "es"
    hashtag_re, link_re = (ES_HASHTAG_RE, ES_LINK_RE) if es else (HASHTAG_RE, LINK_RE)
    concrete_re = ES_CONCRETE_RE if es else CONCRETE_RE
    text = text.rstrip()
    stripped = text.strip()
    chars = len(stripped)
    lines = [l for l in stripped.split("\n")]
    first_line = lines[0].strip() if lines else ""
    tags = hashtag_re.findall(stripped)
    mentions = MENTION_RE.findall(stripped)
    links = link_re.findall(stripped)
    emoji = EMOJI_RE.findall(stripped)
    window = visible_window(stripped, cut)
    truncated = chars > cut
    if es:
        flat = strip_accents(stripped)
        asks = [name for pattern, name in ES_ASKS if pattern.search(flat)]
        filler = [t for t in tags if strip_accents(t) in ES_FILLER_TAGS]
    else:
        asks = [name for pattern, name in ASKS if pattern.search(stripped)]
        filler = [t for t in tags if t.lower() in FILLER_TAGS]
    keywords = [k.strip() for k in (keywords or []) if k.strip()]

    checks = []

    def add(name, status, detail):
        checks.append({"check": name, "status": status, "detail": detail})

    add("LENGTH", "FAIL" if chars > LIMIT else "PASS",
        f"{chars} / {LIMIT} characters" + (f", {chars - LIMIT} over the limit"
                                           if chars > LIMIT else ""))

    if not first_line:
        add("FIRST LINE", "FAIL", "the caption opens on a blank line")
    elif first_line.startswith("#") or first_line.startswith("@"):
        add("FIRST LINE", "FAIL",
            "opens on a hashtag or a mention, which is the one position worth a sentence")
    elif len(first_line) > cut:
        add("FIRST LINE", "WARN",
            f"{len(first_line)} characters, so it gets cut at {cut} mid-thought. "
            "Fine if the cut is a cliffhanger, bad if it is a subordinate clause")
    else:
        add("FIRST LINE", "PASS", f"{len(first_line)} characters, lands whole")

    add("HOOK IS CONCRETE", "PASS" if concrete_re.search(window) else "WARN",
        f"{len(concrete_re.findall(window))} number(s) or name(s) in the visible window"
        + ("" if concrete_re.search(window) else " - nothing checkable before the tap"))

    if len(tags) > HASHTAG_LIMIT:
        add("HASHTAGS", "FAIL", f"{len(tags)} tags, over Instagram's cap of {HASHTAG_LIMIT}. "
                                "Tags past the fifth do not count and the block reads as old")
    elif len(tags) == HASHTAG_LIMIT and filler:
        add("HASHTAGS", "WARN", f"{len(tags)} tags, at the cap, and "
                                f"{len(filler)} of them generic. Spend the five on topics")
    elif filler:
        add("HASHTAGS", "WARN", f"{len(tags)} tags, {len(filler)} of them generic "
                                f"({', '.join(filler[:3])}). Those describe nothing")
    else:
        add("HASHTAGS", "PASS", f"{len(tags)} tag(s)" + (f": {' '.join(tags)}" if tags else ""))

    if not tags:
        add("TAG PLACEMENT", "PASS", "no tags to place")
    elif any(re.search(r"(?:^|\s)" + re.escape(t) + r"\b", window) for t in tags):
        add("TAG PLACEMENT", "WARN", "a hashtag is inside the visible window, "
                                     "spending feed space on a label")
    else:
        add("TAG PLACEMENT", "PASS", "tags are below the fold")

    add("LINKS", "WARN" if links else "PASS",
        f"{len(links)} link(s) in the caption, and captions are not clickable. "
        f"Move it to the bio or the DM" if links else "no dead links in the body")

    if len(asks) == 1:
        add("ONE ASK", "PASS", f"one call to action: {asks[0]}")
    elif not asks:
        add("ONE ASK", "WARN", "no call to action. Decide what this post is for")
    else:
        add("ONE ASK", "WARN", f"{len(asks)} asks ({', '.join(asks)}). "
                               "Two asks is the same as none")

    density = len(emoji) * 100 / max(chars, 1)
    add("EMOJI", "WARN" if density > 4 else "PASS",
        f"{len(emoji)} emoji, {density:.1f} per 100 characters"
        + (" - reads as decoration" if density > 4 else ""))

    if keywords:
        fold = strip_accents if es else str.lower              # Spanish ignores accents ("pagina" finds "página") but not the ñ
        low = fold(stripped)
        found = [k for k in keywords if fold(k) in low]
        missing = [k for k in keywords if fold(k) not in low]
        in_window = [k for k in found if fold(k) in fold(window)]
        status = "PASS" if not missing else ("WARN" if found else "FAIL")
        add("SEARCH TERMS", status,
            f"{len(found)}/{len(keywords)} present"
            + (f", {len(in_window)} in the visible window" if found else "")
            + (f". Missing: {', '.join(missing)}" if missing else ""))

    fails = sum(1 for c in checks if c["status"] == "FAIL")
    warns = sum(1 for c in checks if c["status"] == "WARN")
    verdict = "FIX" if fails else ("REVIEW" if warns else "READY")

    result = {
        "characters": chars, "limit": LIMIT, "truncate_at": cut,
        "visible": window, "truncated": truncated,
        "first_line_chars": len(first_line),
        "hashtags": tags, "mentions": mentions, "links": links,
        "emoji": len(emoji), "asks": asks,
        "checks": checks, "verdict": verdict,
    }
    if es:
        result["lang"] = "es"
    return result


def render(a, out=sys.stdout):
    head = (f"CAPTION LINT  ·  {a['characters']} / {a['limit']} chars  ·  "
            f"{len(a['hashtags'])} hashtags  ·  {len(a['asks'])} ask(s)")
    print("\n" + head, file=out)
    print("=" * max(len(head), 62), file=out)
    render_box(a["visible"], a["truncated"], out=out)
    print("", file=out)
    for c in a["checks"]:
        print(f"  {c['status']:<5} {c['check']:<17} {c['detail']}", file=out)
    print("-" * max(len(head), 62), file=out)
    print(f"  VERDICT  {a['verdict']}\n", file=out)


def main():
    ap = argparse.ArgumentParser(description="Lint an Instagram caption.")
    ap.add_argument("input", nargs="?", default="-", help="caption file, or - for stdin")
    ap.add_argument("--truncate", type=int, default=TRUNCATE,
                    help=f"characters shown before '... more' (default {TRUNCATE})")
    ap.add_argument("--keywords", default="", help="comma-separated terms you want to be found for")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--lang", choices=["auto", "en", "es"], default="auto",
                    help="language of the caption (default: detect it)")
    args = ap.parse_args()

    raw = sys.stdin.read() if args.input == "-" else open(args.input, encoding="utf-8").read()
    lang = args.lang if args.lang != "auto" else detect_lang(raw)
    if lang == "es":
        print(f"language: Spanish ({'forced' if args.lang != 'auto' else 'detected'})", file=sys.stderr)
    a = analyse(raw, cut=args.truncate, keywords=args.keywords.split(","), lang=lang)
    if args.json:
        print(json.dumps(a, indent=2, ensure_ascii=False))
    else:
        render(a)
    sys.exit(0 if a["verdict"] == "READY" else 1)


if __name__ == "__main__":
    main()
