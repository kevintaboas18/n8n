# Spanish hook sets

Four files of 12 hooks each, written by hand while building the Spanish hook panel:

- `good_B.txt`, `bad_B.txt` - written first and used while the panel was being tuned, so the
  panel was fitted to them. Treat the result on this pair as a smoke test, not as evidence.
- `good_C.txt`, `bad_C.txt` - written afterwards and not used to tune anything.

"Good" means the kind of hook the formulas in `ig-reel/hooks.es.json` describe: a figure, a
cost, a named reader. "Bad" means greetings, preambles, filler and hooks with nothing concrete.

What they can show: that the panel puts the good ones above the bad ones. What they cannot
show: that the panel separates the hooks that worked from the hooks that did not. That is a much
harder question (the upstream author measured 0.56, close to a coin flip, for the English panel
on it), and it has not been measured for Spanish. No hook here comes from a real reel.

`test_lang_es.py` recomputes the numbers quoted in `CONNECT.md` from these files.
