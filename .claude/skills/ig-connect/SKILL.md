---
name: ig-connect
description: >-
  Read the user's own Instagram account through Meta's official API - profile,
  recent posts, per-post insights and, if the token allows it, comments - so
  /ig-audit, /ig-profile and /ig-reply can work from real numbers instead of
  screenshots. Read-only: it never posts, replies or messages. Use when the user
  says "connect my Instagram", "pull my analytics", "read my insights", "sync my
  posts", "check my token", "is the connection working", or before /ig-audit,
  /ig-profile or /ig-reply when the user has not pasted any data.
---

# ig-connect

The one skill in this pack that talks to Instagram, and it only reads. Everything
the other skills write still goes out by the user's own hand.

One tool lives in this folder and it runs. Use the absolute path of this folder,
since the working directory is usually the repo root.

```bash
python3 igapi.py doctor            # is the token alive, and what can it read
python3 igapi.py me                # profile
python3 igapi.py media             # recent posts, with their ids
python3 igapi.py insights          # per-post numbers and the ratios /ig-audit ranks on
python3 igapi.py comments POST_ID  # comments on one post
python3 igapi.py refresh           # extend the token's 60-day life
```

Every command takes `--json`. `media` and `insights` take `--limit`, `--since
YYYY-MM-DD` and `--type feed|reels`.

## First: is it connected?

Run `doctor`. It prints PASS, WARN or FAIL per check and never prints the token.

- **TOKEN FAIL, exit 3.** Not set up, expired or revoked. Send the user to
  `instagram-agent-skill/CONNECT.md`. The token is read from the environment
  variable `IG_ACCESS_TOKEN` and nowhere else. Do not ask the user to paste it
  into the chat, do not offer to store it in a file, and do not look for another
  way in. If they paste one anyway, say it is now in the conversation and they
  should revoke it and generate a new one.
- **INSIGHTS or COMMENTS FAIL, exit 4.** The token lacks a permission. Say which
  (insights: `instagram_business_manage_insights`; comments:
  `instagram_business_manage_comments`) and carry on with pasted data meanwhile.
- **EXPIRY WARN.** Run `refresh` now. The token must be at least 24 hours old and
  not yet expired. After 60 days without a refresh it cannot be refreshed at all.
- **VERDICT READY or PARTIAL.** Go ahead.

## Which command feeds which skill

| skill | run | replaces |
| --- | --- | --- |
| `/ig-audit` | `insights --limit 30 --json` | screenshots of post insights |
| `/ig-profile` | `me --json` | the pasted name field, bio and link |
| `/ig-reply` | `media`, then `comments POST_ID --json` | pasted comments |
| `/ig-plan` | `insights --limit 30` | guessing which themes landed |

Summarise for the user. Do not dump the JSON. Name the sample size, because
twelve posts show a pattern at best.

## What the API will not give you

Say so instead of papering over it, and ask for a screenshot where it matters.

- **Hold at 3 seconds and the retention graph.** Not exposed. For Reels there is
  `reels_skip_rate`, Meta's estimate of views skipped in the first three seconds.
  Its unit is not stated in the documentation this was written from, so check it
  against the app before treating it as hold at 3s.
- **The non-follower share of reach per post.** Not exposed.
- **Follows per reach for Reels.** `follows` is only reported for feed posts.
- **Highlights, pinned posts and the grid.** Not exposed. Ask for them.
- **Fresh numbers.** Insights can lag up to 48 hours, so the newest posts may be
  incomplete or empty. An empty post is not a flop.
- **Fields Meta withholds from this kind of token.** The script lists them under
  "Not readable". The bio and website may be among them.

## Rules

- **Read-only.** If the user asks to post, reply, hide, follow or message through
  this skill, say it does not, and carry on drafting in the other skills.
- **The token never appears** in a command line, a file, a commit or a message.
- **Private data stays out of the repo.** Insights and other people's comments
  are private, and a repository can be public. `--out` refuses paths inside a git
  repository, and that is deliberate. Use a path such as
  `~/.claude/instagram/audit.json`. Do not work around the refusal.
- **Comments belong to other people.** Use them to draft replies. Do not quote
  handles anywhere outside this task.
- **Nothing is fabricated.** A number the API did not return is "not available",
  never an estimate dressed up as a reading.

## Exit codes

0 ok, 1 other error, 2 usage, 3 token, 4 permission, 5 rate limit, 6 network. For
5, wait and retry with a smaller `--limit`. For 6, check the environment's
network access to `graph.instagram.com`.
