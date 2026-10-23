# Provenance

`.claude/skills/ig-*` and the files in this directory are an unmodified copy of
[Jakeschincariol/instagram-agent-skill](https://github.com/Jakeschincariol/instagram-agent-skill)
v1.0.0, MIT licensed, copyright (c) 2026 Jake Schincariol. `LICENSE` here is the
upstream license and has to travel with any copy.

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
