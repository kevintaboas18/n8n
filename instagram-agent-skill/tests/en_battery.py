"""
A fixed battery of English inputs for the six text tools, and a runner that records
exactly what they print.

Why it exists: Spanish support was added to those tools on the promise that English
behaves exactly as before. The golden transcript in golden/en.json was recorded from
the untouched upstream scripts, and test_english_unchanged.py replays this battery
against today's scripts and demands an identical transcript.

Regenerate the golden file only from pristine upstream scripts, never from edited
ones (see make_golden.py).
"""

import json
import os
import subprocess
import sys
import tempfile

HOOKS = """\
Nobody tells you that your first 30 reels are supposed to flop.
I lost $18,000 because of one missing contract.
Stop scrolling if you want to grow on Instagram in 2026 \U0001F525
Hey guys, today I wanted to talk about content strategy
Steal this four line follow up it took me two years
Zero dollars. That is what my first client paid me.
In this video I'm going to show you how to grow
Why nobody talks about the real cost of freelancing in the first year of business and what you can do about it today
Don't do this
33% of freelancers never raise their prices.
If your reels get views and no followers, the next 40 seconds fix it.
This used to take me five hours. Now it takes twenty minutes.
Quit your job #entrepreneur
"""

SCRIPT = """\
I lost $18,000 because of one missing contract.
Here is the exact clause I now put in every single contract I send to a new client, and I will read it to you word for word right now.
Section 4. Payment on delivery, not on approval.
Approval is a feeling. Delivery is a date.
That one word change is worth $18,000 to me.
"""

LONG_SCRIPT = (
    "Most freelancers think pricing is a math problem and it is not. It is a story you tell yourself about "
    "what you are worth and what the market will bear, and the story changes the number every single time. "
    "When I raised my rates I expected the phone to stop ringing. Instead the phone rang less and the calls "
    "got better, and that was the whole lesson of the year for me.\n"
)

ABSTRACT_SCRIPT = """\
This is about something important that matters a lot.
It is the kind of thing that changes how you think about it.
Everything comes down to doing the right thing consistently.
Think about what that means for you and for them.
"""

CAPTION = """\
I lost $18,000 because of one missing clause in a contract, and the worst part is that I had read the thing twice before I signed it.

If you run a small agency, the clause that matters is payment on delivery, not on approval. Client contracts are where freelance pricing goes to die.

Comment CONTRACT and I will send you the clause.

#freelance #contracts #agencyowner
"""

CAPTION_BAD = """\
#viral #fyp #reels #explorepage #trending #love #follow #instagood
Hey everyone!!! \U0001F525\U0001F525\U0001F525 Check this out at https://example.com/now and www.example.org/x and save this, share this, follow me, DM me for the link in bio. Tell me which one you like ✨✨✨ \U0001F680\U0001F680
"""

SLOP = (
    "In today’s fast-paced world, it’s not just about content — it’s about connection. "
    "Let’s delve into how you can leverage a robust strategy.​ Stop scrolling! \U0001F680 Follow for more.\n"
)

SLOP_2 = (
    "Picture this: you have a seamless workflow, plus a comprehensive plan – and 5–10 clients. "
    "Furthermore, the landscape is changing. Check https://example.com/a—b and mail me@example.com. "
    "The result?\nRead that again.\n- Save time\n- Save money\n- Save effort\n\U0001F4A1 Tip one\n"
    "Not only is it fast but also cheap. Thoughts?\n"
)

HUMAN = (
    "I raised my prices by 40% last March and lost exactly one client. He was the one taking up half my inbox. "
    "It took me eight months to stop being scared of the number. Here's what I'd tell anyone starting out: "
    "you don't need permission, you need three invoices. We tried discounts in June and they didn't work. "
    "Nobody on my team liked it either, so we dropped it.\n"
)

SWIPE_MEDIAN = (
    "account\tfollowers\tmedian\tviews\thook\n"
    "@a\t50000\t11000\t412000\tnobody tells you that your first 30 reels are supposed to flop\n"
    "@b\t2000000\t900000\t1200000\tin this video I am going to show you my morning routine\n"
    "@c\t4000\t3000\t180000\tsteal this four line follow up it took me two years\n"
    "@d\t9000\t2500\t30000\tI lost $18,000 because of one missing contract\n"
    "@e\t1500\t800\t900\tstop posting daily\n"
)

SWIPE_FOLLOWERS = (
    "account\tfollowers\tviews\thook\n"
    "@a\t50000\t412000\tmy first 47 reels did nothing\n"
    "@b\t2000000\t1200000\tthe fastest way to get confident\n"
)

SWIPE_HEADERLESS = "@a\t50000\t412000\tcarousels vs reels i ran both for 90 days\n"

CASES = [
    # name, script, args, files, stdin, files to read back
    ("hookscore-single", "ig-reel/hookscore.py", ["--hook", "I lost $18,000 because of one missing contract."], {}, None, []),
    ("hookscore-bad-single", "ig-reel/hookscore.py", ["--hook", "Hey guys, today I wanted to talk about content"], {}, None, []),
    ("hookscore-many", "ig-reel/hookscore.py", ["{hooks}"], {"hooks": HOOKS}, None, []),
    ("hookscore-many-json", "ig-reel/hookscore.py", ["{hooks}", "--json"], {"hooks": HOOKS}, None, []),
    ("hookscore-stdin", "ig-reel/hookscore.py", ["-"], {}, HOOKS, []),
    ("hookscore-empty", "ig-reel/hookscore.py", ["{empty}"], {"empty": "\n"}, None, []),
    ("beats-plain", "ig-reel/beats.py", ["{script}"], {"script": SCRIPT}, None, []),
    ("beats-target", "ig-reel/beats.py", ["{script}", "--target", "30", "--wpm", "185"], {"script": SCRIPT}, None, []),
    ("beats-json", "ig-reel/beats.py", ["{script}", "--json", "--target", "20"], {"script": SCRIPT}, None, []),
    ("beats-long", "ig-reel/beats.py", ["{script}", "--target", "45"], {"script": LONG_SCRIPT}, None, []),
    ("beats-abstract", "ig-reel/beats.py", ["{script}"], {"script": ABSTRACT_SCRIPT}, None, []),
    ("beats-empty", "ig-reel/beats.py", ["{script}"], {"script": "\n\n"}, None, []),
    ("caption-good", "ig-caption/caption.py", ["{cap}", "--keywords", "client contracts,freelance pricing"], {"cap": CAPTION}, None, []),
    ("caption-good-json", "ig-caption/caption.py", ["{cap}", "--json"], {"cap": CAPTION}, None, []),
    ("caption-bad", "ig-caption/caption.py", ["{cap}", "--keywords", "pricing"], {"cap": CAPTION_BAD}, None, []),
    ("caption-truncate", "ig-caption/caption.py", ["{cap}", "--truncate", "60"], {"cap": CAPTION}, None, []),
    ("caption-stdin", "ig-caption/caption.py", ["-"], {}, CAPTION, []),
    ("humanize-slop-report", "ig-human/humanize.py", ["{t}", "--report"], {"t": SLOP}, None, []),
    ("humanize-slop2-report", "ig-human/humanize.py", ["{t}", "--report"], {"t": SLOP_2}, None, []),
    ("humanize-json", "ig-human/humanize.py", ["{t}", "--json"], {"t": SLOP_2}, None, []),
    ("humanize-human", "ig-human/humanize.py", ["{t}", "--report"], {"t": HUMAN}, None, []),
    ("humanize-out", "ig-human/humanize.py", ["{t}", "-o", "{o}", "--report"], {"t": SLOP, "o": ""}, None, ["o"]),
    ("detect-slop", "ig-human/detect.py", ["{t}"], {"t": SLOP_2}, None, []),
    ("detect-human", "ig-human/detect.py", ["{t}"], {"t": HUMAN}, None, []),
    ("detect-json", "ig-human/detect.py", ["{t}", "--json"], {"t": SLOP_2}, None, []),
    ("detect-compare", "ig-human/detect.py", ["{a}", "{b}"], {"a": SLOP_2, "b": HUMAN}, None, []),
    ("swipe-median", "ig-viral/swipe.py", ["{tsv}"], {"tsv": SWIPE_MEDIAN}, None, []),
    ("swipe-median-json", "ig-viral/swipe.py", ["{tsv}", "--json"], {"tsv": SWIPE_MEDIAN}, None, []),
    ("swipe-followers", "ig-viral/swipe.py", ["{tsv}"], {"tsv": SWIPE_FOLLOWERS}, None, []),
    ("swipe-headerless", "ig-viral/swipe.py", ["{tsv}"], {"tsv": SWIPE_HEADERLESS}, None, []),
    ("swipe-out", "ig-viral/swipe.py", ["{tsv}", "--out", "{o}"], {"tsv": SWIPE_MEDIAN, "o": ""}, None, ["o"]),
    ("swipe-empty", "ig-viral/swipe.py", ["{tsv}"], {"tsv": "account\tviews\thook\n"}, None, []),
]


def transcript(root):
    """Run every case against the scripts under `root` (…/ig-reel, …/ig-human …)."""
    result = {}
    for name, script, args, files, stdin, readback in CASES:
        with tempfile.TemporaryDirectory() as tmp:
            paths = {}
            for key, content in files.items():
                paths[key] = os.path.join(tmp, key + ".txt")
                if content:
                    with open(paths[key], "w", encoding="utf-8") as fh:
                        fh.write(content)
            cmd = [sys.executable, "-I", "-B", os.path.join(root, script)]
            cmd += [a.format(**paths) if "{" in a else a for a in args]
            run = subprocess.run(cmd, input=stdin, capture_output=True, text=True, timeout=60)
            entry = {"exit": run.returncode,
                     "stdout": run.stdout.replace(tmp, "<TMP>"),
                     "stderr": run.stderr.replace(tmp, "<TMP>")}
            for key in readback:
                try:
                    with open(paths[key], encoding="utf-8") as fh:
                        entry["file:" + key] = fh.read()
                except OSError:
                    entry["file:" + key] = None
            result[name] = entry
    return result


if __name__ == "__main__":
    print(json.dumps(transcript(sys.argv[1]), indent=1, ensure_ascii=False, sort_keys=True))
