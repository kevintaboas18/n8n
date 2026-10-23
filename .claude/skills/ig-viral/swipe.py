#!/usr/bin/env python3
"""
swipe.py - rank reels you collected by how far they beat their own account,
name the hook formula each one used, and write the swipe file.

The point of this script is one correction: raw views are not evidence. A
2,000,000-follower account doing 400,000 views had a quiet day. A 4,000-
follower account doing 400,000 views found something. This ranks on the
multiple over the account's own baseline, which is the only version of
"went viral" that tells you anything you can copy.

Input is a tab-separated file you fill in while you browse, one reel per row,
with a header line naming the columns:

    account   followers   median   views    hook
    @someone  48000       11000    412000   nobody tells you your first 30 flop

`median` is that account's typical recent views and is the better baseline.
If you only have `followers`, leave median out and the script says so.
`hook` is the first line of the reel, spoken or on screen, in their words.

Usage
  python3 swipe.py captured.tsv
  python3 swipe.py captured.tsv --out ~/.claude/instagram/swipe.md
  python3 swipe.py captured.tsv --json
  python3 swipe.py capturados.tsv     # Spanish hooks are detected on their own; the header may read
                                      # cuenta  seguidores  mediana  vistas  gancho
"""

import argparse
import json
import os
import re
import statistics
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
HOOKS = os.path.join(HERE, "..", "ig-reel", "hooks.json")
WORD_RE = re.compile(r"[A-Za-z0-9$%'’-]+")

try:                                              # optional: score the hooks too
    sys.path.insert(0, os.path.join(HERE, "..", "ig-reel"))
    from hookscore import run as score_hook       # noqa: E402
except Exception:                                 # ig-viral copied on its own
    score_hook = None


def load_formulas(path):
    try:
        d = json.load(open(path, encoding="utf-8"))
    except Exception:
        return None
    by_id = {h["id"]: h for h in d["hooks"]}
    order = d.get("classify_order") or sorted(by_id)
    return [(by_id[i]["id"], by_id[i]["name"],
             re.compile(by_id[i]["match"], re.IGNORECASE)) for i in order if i in by_id]


def classify(hook, formulas):
    if not formulas:
        return None, "unclassified"
    for fid, name, pattern in formulas:
        if pattern.search(hook):
            return fid, name
    return None, "unclassified"


# ---------------------------------------------------------------------------
# Spanish
#
# Added beside the English code, which is untouched. A hook is Spanish if it reads as Spanish
# (detected per hook, or --lang es): it is named against ig-reel/hooks.es.json, scored by
# hookscore's Spanish panel, and its words are counted with accented letters kept whole. Both
# files use the same 26 ids, so "#3" is the same formula in either language, and the table always
# prints the English formula name so a mixed batch adds up. Spanish column headers
# (cuenta, seguidores, mediana, vistas, gancho) are accepted. A first version, not tuned on a
# corpus of real Spanish reels.
# ---------------------------------------------------------------------------

HOOKS_ES = os.path.join(HERE, "..", "ig-reel", "hooks.es.json")
ES_WORD_RE = re.compile(r"[A-Za-z0-9ÁÉÍÓÚÜÑáéíóúüñ$%'’-]+")
ES_HEADERS = {"cuenta": "account", "seguidores": "followers", "mediana": "median", "vistas": "views",
              "visualizaciones": "views", "reproducciones": "views", "gancho": "hook"}


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


def load_formulas_es(path):
    """Spanish formulas as (id, English name, Spanish name, pattern), in classify order."""
    try:
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
    except Exception:
        return None
    by_id = {h["id"]: h for h in d["hooks"]}
    order = d.get("classify_order") or sorted(by_id)
    return [(by_id[i]["id"], by_id[i].get("name_en", by_id[i]["name"]), by_id[i]["name"],
             re.compile(by_id[i]["match"], re.IGNORECASE)) for i in order if i in by_id]


def classify_es(hook, formulas_es):
    """Patterns run on the accent-stripped, lower-cased hook."""
    if not formulas_es:
        return None, "unclassified", None
    folded = strip_accents(hook)
    for fid, name_en, name_es, pattern in formulas_es:
        if pattern.search(folded):
            return fid, name_en, name_es
    return None, "unclassified", None


def read_rows(path):
    raw = sys.stdin.read() if path == "-" else open(path, encoding="utf-8").read()
    lines = [l for l in raw.splitlines() if l.strip() and not l.lstrip().startswith("#")]
    if not lines:
        return []
    head = [ES_HEADERS.get(c, c) for c in (c.strip().lower() for c in lines[0].split("\t"))]
    if "views" in head and "hook" in head:
        cols, body = head, lines[1:]
    else:
        cols, body = ["account", "followers", "views", "hook"], lines
    rows = []
    for line in body:
        cells = line.split("\t")
        if len(cells) < len(cols):
            cells += [""] * (len(cols) - len(cells))
        r = dict(zip(cols, [c.strip() for c in cells]))
        try:
            r["views"] = int(re.sub(r"[^\d]", "", r.get("views", "")) or 0)
        except ValueError:
            continue
        for k in ("followers", "median"):
            digits = re.sub(r"[^\d]", "", r.get(k, "") or "")
            r[k] = int(digits) if digits else None
        if r["views"] and r.get("hook"):
            rows.append(r)
    return rows


def analyse(rows, formulas, formulas_es=None, lang="auto"):
    used_median = any(r.get("median") for r in rows)
    for r in rows:
        base = r.get("median") or r.get("followers") or 0
        r["baseline"] = base
        r["outlier"] = round(r["views"] / base, 2) if base else None
        if (lang if lang != "auto" else detect_lang(r["hook"])) == "es":
            r["lang"] = "es"
            r["formula_id"], r["formula"], name_es = classify_es(r["hook"], formulas_es)
            if name_es:
                r["formula_es"] = name_es
            r["words"] = len(ES_WORD_RE.findall(re.sub(r"(?<=\d)[.,](?=\d)", "", r["hook"])))   # 18.000 is one word
            if score_hook:
                try:
                    _, overall, verdict, _ = score_hook(r["hook"], "es")
                    r["hook_score"], r["hook_verdict"] = round(overall, 1), verdict
                except TypeError:                     # an older hookscore.py with no Spanish panel
                    r["hook_score"], r["hook_verdict"] = None, None
            else:
                r["hook_score"], r["hook_verdict"] = None, None
            continue
        r["formula_id"], r["formula"] = classify(r["hook"], formulas)
        r["words"] = len(WORD_RE.findall(r["hook"]))
        if score_hook:
            _, overall, verdict, _ = score_hook(r["hook"])
            r["hook_score"], r["hook_verdict"] = round(overall, 1), verdict
        else:
            r["hook_score"], r["hook_verdict"] = None, None
    ranked = sorted(rows, key=lambda r: -(r["outlier"] or 0))
    third = max(1, len(ranked) // 3)
    top, bottom = ranked[:third], ranked[-third:]

    def med(items, key):
        vals = [i[key] for i in items if i.get(key) is not None]
        return round(statistics.median(vals), 1) if vals else None

    counts = {}
    for r in top:
        counts[r["formula"]] = counts.get(r["formula"], 0) + 1
    return {
        "baseline": "account median" if used_median else "follower count",
        "n": len(ranked),
        "accounts": len({r.get("account", "") for r in ranked}),
        "reels": ranked,
        "top_formulas": sorted(counts.items(), key=lambda kv: -kv[1]),
        "top_hook_score": med(top, "hook_score"),
        "bottom_hook_score": med(bottom, "hook_score"),
        "top_words": med(top, "words"),
        "bottom_words": med(bottom, "words"),
        "unclassified": sum(1 for r in ranked if r["formula"] == "unclassified"),
    }


def render(a, out=sys.stdout):
    head = (f"SWIPE FILE  ·  {a['n']} reels  ·  {a['accounts']} accounts  ·  "
            f"baseline: {a['baseline']}")
    print("\n" + head, file=out)
    print("=" * max(len(head), 78), file=out)
    for r in a["reels"]:
        mult = f"{r['outlier']:.1f}x" if r["outlier"] else "   ?"
        score = f"{r['hook_score']:.0f}" if r["hook_score"] is not None else " -"
        fid = f"#{r['formula_id']:<2}" if r["formula_id"] else "-  "
        print(f"  {mult:>7}  hook {score:>3}  {fid} {r['formula'][:22]:<22} "
              f"{r.get('account', '')[:16]:<16} {r['views']:>9,}", file=out)
        print(f"           \"{r['hook'][:96]}\"", file=out)
    print("-" * max(len(head), 78), file=out)
    print("WHAT IS WORKING IN THIS BATCH", file=out)
    if a["top_formulas"]:
        print("  top third by outlier:  "
              + ", ".join(f"{n} x{c}" for n, c in a["top_formulas"][:4]), file=out)
    if a["top_hook_score"] is not None:
        print(f"  median hook score:     top {a['top_hook_score']:.0f}  "
              f"vs bottom {a['bottom_hook_score']:.0f}", file=out)
    print(f"  median hook length:    top {a['top_words']} words  "
          f"vs bottom {a['bottom_words']} words", file=out)
    print(f"  unclassified:          {a['unclassified']} of {a['n']}. Read those by hand, "
          "they are where a formula you do not have yet is hiding.", file=out)
    print("\n  A hand-collected batch is evidence, not proof. Twelve reels shows you "
          "nothing;\n  forty across six accounts shows you something. Collect more before "
          "you believe it.\n", file=out)


def to_markdown(a):
    lines = ["# Swipe file", "",
             f"{a['n']} reels across {a['accounts']} accounts. "
             f"Ranked by multiple over {a['baseline']}.", ""]
    for r in a["reels"]:
        mult = f"{r['outlier']:.1f}x" if r["outlier"] else "?"
        lines += [f"## {mult}  {r['formula']}  ({r.get('account', '')})",
                  f"- views: {r['views']:,}  baseline: {r['baseline']:,}",
                  f"- hook score: {r['hook_score']}  words: {r['words']}",
                  f"- hook: \"{r['hook']}\"", ""]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description="Rank collected reels by outlier multiple.")
    ap.add_argument("input", nargs="?", default="-", help="TSV file, or - for stdin")
    ap.add_argument("--hooks", default=HOOKS, help="path to ig-reel/hooks.json")
    ap.add_argument("--hooks-es", default=HOOKS_ES, help="path to ig-reel/hooks.es.json (Spanish hooks)")
    ap.add_argument("--lang", choices=["auto", "en", "es"], default="auto",
                    help="language of the hooks (default: detect it for each hook)")
    ap.add_argument("--out", help="also write the swipe file as markdown here")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    rows = read_rows(args.input)
    if not rows:
        print("no usable rows. Need a tab-separated file with at least views and hook.",
              file=sys.stderr)
        sys.exit(2)
    formulas = load_formulas(args.hooks)
    formulas_es = load_formulas_es(args.hooks_es)
    a = analyse(rows, formulas, formulas_es, args.lang)
    spanish = sum(1 for r in a["reels"] if r.get("lang") == "es")
    if spanish:
        print(f"language: {spanish} Spanish hook(s) of {a['n']} "
              f"({'forced' if args.lang != 'auto' else 'detected'}); Spanish formulas and hook panel are "
              "a first version, not tuned on real Spanish reels.", file=sys.stderr)
        if not formulas_es:
            print("note: hooks.es.json not found, Spanish formulas not named. Pass --hooks-es.", file=sys.stderr)
    if not formulas:
        print("note: hooks.json not found, formulas not named. Pass --hooks.", file=sys.stderr)
    if score_hook is None:
        print("note: hookscore.py not importable, hook scores skipped.", file=sys.stderr)

    if args.json:
        print(json.dumps(a, indent=2, ensure_ascii=False))
    else:
        render(a)
    if args.out:
        path = os.path.expanduser(args.out)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w", encoding="utf-8").write(to_markdown(a))
        print(f"wrote {path}", file=sys.stderr)


if __name__ == "__main__":
    main()
