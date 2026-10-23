# Provenance

`.claude/skills/ig-*` and the files in this directory are a copy of
[Jakeschincariol/instagram-agent-skill](https://github.com/Jakeschincariol/instagram-agent-skill)
v1.0.0, MIT licensed, copyright (c) 2026 Jake Schincariol. `LICENSE` here is the
upstream license and has to travel with any copy. Anything not listed under
"Local changes" below is byte-identical to the snapshot. Six scripts and four
`SKILL.md` files were later changed to add Spanish; see "Spanish support" for the
exact list and for how English was kept as it was.

- **Snapshot:** `main` at `d03c56bb598be770c60b201f94237e5d1a4268a6`, read from the
  comment embedded in the downloaded zip. Not re-checked against GitHub.
- **Imported:** 2026-10-23, from a zip uploaded by the repo owner.

| upstream path | path here |
| --- | --- |
| `skills/ig-*/` | `.claude/skills/ig-*/` |
| `LICENSE`, `README.md` | `instagram-agent-skill/` |
| `templates/voice.md` | `instagram-agent-skill/templates/voice.md` |

Left out: `.claude-plugin/` (plugin and marketplace manifests, only used by
`/plugin install`) and the upstream `.gitignore`.

Things to know before relying on it:

- The relative links in `README.md` follow the upstream layout and do not resolve here.
- The skills keep their state in `~/.claude/instagram/` (`voice.md`, `swipe.md`,
  `log.md`, `plan.md`), which is the user's home directory and not this repo.
  Copy `templates/voice.md` there and fill it in before the first run.
- The skills write copy for a human to post. None of them posts, comments or
  messages on Instagram.
- Do not edit these files in place without recording the change here, so the
  copy stays diffable against upstream.

## Known issues found on import

Not fixed, so the copy stays identical to upstream.

- `ig-viral/swipe.py --out swipe.md` (a bare filename) crashes with
  `FileNotFoundError`, because `os.makedirs` is called on an empty directory
  name. `--out some/dir/swipe.md` works. Verified by running it.
- `ig-human/slop.json` rewrites legitimate words with no context check:
  "landscape" -> "market", "journey" -> "process", "iconic" -> "known",
  "stunning" -> "good", "foster" -> "build", "harness" -> "use". Read the
  `--report` output before using the cleaned text. Verified by running it.
- The hashtag cap of 5 per post (`ig-caption/caption.py`, `ig-caption/SKILL.md`)
  is a platform fact the pack hardcodes. Not verified here; check it against
  Instagram's current help pages.
- The `hashtag-wall` entry in `slop.json` says "LinkedIn stopped rewarding the
  wall", a leftover from the author's LinkedIn pack. Cosmetic.
- `ig-human/humanize.py` leaves orphan punctuation when it deletes a phrase in the
  middle of a text: "Hello. Let's face it, the thing works." becomes
  "Hello., the thing works." (full stop, comma, lower case). The Spanish pass does
  not have this problem. Verified by running it.
- `ig-reel/hooks.json`: 6 of the 26 filled examples (formulas 7, 8, 11, 12, 14, 19)
  are not classified as their own formula by the `match` regexes next to them
  (for instance "Five caption edits that double saves..." fails because the regex
  wants a digit). So `ig-viral/swipe.py` names formulas approximately. Verified by
  running every example through `classify_order`.
- Several upstream scripts leave files for the garbage collector to close
  (`open(...).read()`, `json.load(open(...))`). Harmless in a short-lived script;
  it only shows up when Python runs with `-W error::ResourceWarning`.

## Local changes

Made at the repo owner's request, after the import. Everything else under
`.claude/skills/ig-*` and in this directory is byte-identical to the snapshot.

- **`ig-connect` (new skill).** `.claude/skills/ig-connect/`: a read-only client for
  Meta's Instagram API with Instagram Login, so `ig-audit`, `ig-profile` and
  `ig-reply` can use real numbers. Standard library only, GET requests only, the
  token from `IG_ACCESS_TOKEN` only. Not part of upstream.
- **`CONNECT.md`** (Spanish): how to create the Meta app and the token.
- **`tests/test_igapi.py`**: 29 tests against a local stand-in for the API.
- **`ig-audit`, `ig-profile`, `ig-reply` `SKILL.md`**: one paragraph each, under their
  Input section, pointing at `ig-connect`.
- **`.gitignore`** (repo root): Python bytecode, `.env*`, `*.token`.

## Spanish support

Made at the repo owner's request: they publish in Spanish and English, one piece per
language, and asked for Spanish in the text tools with English kept as it was.

**Changed (additions beside the English code, plus a few lines in `main`/`render`):**

| file | what was added |
| --- | --- |
| `ig-reel/hookscore.py` | Spanish hook panel (five checks), `--lang`, per-hook language detection |
| `ig-reel/beats.py` | Spanish words (a number like `18.000` is one word), concreteness, echo of the hook, `--lang` |
| `ig-caption/caption.py` | accented hashtags, Spanish asks and filler tags, accent-folded search terms, `--lang` |
| `ig-human/humanize.py` | Spanish lexicon pass, dialogue-dash rule, deletion clean-up, `--lang` |
| `ig-human/detect.py` | Spanish panel (no contractions term, calendar words count as concrete), `--lang` |
| `ig-viral/swipe.py` | Spanish hook naming and scoring, Spanish column names, `--lang`, `--hooks-es` |
| `ig-reel/SKILL.md`, `ig-caption/SKILL.md`, `ig-human/SKILL.md`, `ig-viral/SKILL.md` | a "Language" section each |

**New data files:** `ig-human/slop.es.json` (94 stock words and phrases, 17 structural
tells; invisible characters and typography are read from `slop.json`) and
`ig-reel/hooks.es.json` (the same 26 formulas, same ids and order, in Spanish).

**How English was kept as it was.** `tests/golden/en.json` is what the six tools printed
for 32 English cases (`tests/en_battery.py`) when they were the untouched upstream
scripts, recorded from commit `a6fb7a4`. `tests/test_english_unchanged.py` replays
the battery against today's scripts and demands the same exit code, stdout, stderr and
output files, character for character. It was re-run after each stage of the work and
passes on the final state. It covers
32 cases, not every code path: a behaviour outside those cases is not proven identical.
`git diff a6fb7a4 -- .claude/skills/ig-reel/hookscore.py` shows the rest.

**Language detection** is the same function, copied into each script so each skill
folder stays self-contained (`tests/test_lang_es.py` checks the six copies are the same
source). It counts Spanish and English stop words plus `¿ ¡ ñ` and accents, and falls back
to English when it finds nothing: a string with no stop word, such as `CARRUSELES vs
REELS`, is read as English. `--lang es|en` forces it.

**What was and was not checked.**

- Checked, and covered by tests: that English is unchanged on the 32 cases; that the
  detector agrees across the six scripts and classifies 10 short Spanish and 10 English
  hooks as intended; that the two Spanish data files are well formed; that the Spanish
  clean-up handles a list of edge cases (deleted openers, parenthetical commas, `a fin de
  cuentas`, `etc.,`, dialogue dashes); that `swipe.py` reads Spanish headers and mixed
  batches.
- Checked on my own examples only: the hook panel orders 144 of 144 good/bad pairs on
  set B (the set it was tuned on) and 137 of 144 on set C (written afterwards), and marks 11
  of the 12 bad hooks in C as WEAK. Sets are in `tests/es_hooks/`. They were written by
  the same hand as the word lists. This is a much easier question than whether the panel
  can tell a creator's hits from their misses, which the upstream author measured at 0.56
  for English (a coin flip is 0.50) and which has not been measured for Spanish.
- Not checked: any real Spanish caption, voiceover or reel. The Spanish lexicon, the
  hook formulas' `match` patterns and every threshold (carried over from English) are a
  first version. 51 of the 94 lexicon entries are report-only because Spanish verbs and
  adjectives inflect and a blind swap writes broken grammar.
- Mistakes found and fixed while testing, kept as regression tests: a copied line that
  counted every space as a hard space; `a fin de` turning `a fin de cuentas` into
  `para cuentas`; a language threshold that read short Spanish hooks as English; a
  first-person check that needed the accent.

**Run the tests:** `python3 -I -B -W error::ResourceWarning -m unittest discover -s
instagram-agent-skill/tests -p "test_*.py"`.
