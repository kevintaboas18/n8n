#!/usr/bin/env python3
"""
igapi.py - read your own Instagram account through Meta's official API.

Read-only by design. Every request this script makes is an HTTP GET. It never
posts, comments, replies, messages, follows, likes or deletes, and it contains
no code that could. Even `refresh`, which extends the token's life, is a GET.

What it needs: an Instagram professional account (Business or Creator) and an
access token from Meta's "Instagram API with Instagram Login", set in the
environment as IG_ACCESS_TOKEN. The token is never taken from the command line,
never printed and never written to disk. Setup: instagram-agent-skill/CONNECT.md.

Usage
  python3 igapi.py doctor [--comments]
  python3 igapi.py me
  python3 igapi.py media    [--limit 25] [--since 2026-09-01] [--type all|feed|reels]
  python3 igapi.py insights [--limit 25] [--since 2026-09-01] [--type all|feed|reels]
  python3 igapi.py comments MEDIA_ID [--limit 50]
  python3 igapi.py refresh [--print-new-token]
  add --json for machine output, --out FILE to also save it as JSON
  (--out is refused inside a git repository: this data is private)

Environment
  IG_ACCESS_TOKEN   required
  IG_TOKEN_ISSUED   optional, YYYY-MM-DD, lets `doctor` warn before the 60 days run out
  IG_API_VERSION    optional, default v26.0 (the version Meta's docs use today)

Meta changes this API often. The field and metric lists below follow Meta's
published reference, but a few could not be confirmed for every account, so the
script drops any field or metric Meta rejects and says so, instead of failing.

Exit codes: 0 ok, 1 error, 2 usage, 3 token, 4 permission, 5 rate limit, 6 network.
"""

import argparse
import datetime as dt
import json
import os
import re
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_BASE = "https://graph.instagram.com"
DEFAULT_VERSION = "v26.0"
TOKEN_ENV = "IG_ACCESS_TOKEN"
TOKEN_LIFETIME_DAYS = 60
MAX_CALLS = 400            # hard stop per run, so a loop can never hammer the API
MAX_BYTES = 8_000_000      # response size cap

EXIT = {"ok": 0, "error": 1, "usage": 2, "token": 3, "permission": 4, "rate": 5, "network": 6}

PROFILE_FIELDS = ["user_id", "username", "name", "account_type", "profile_picture_url",
                  "followers_count", "follows_count", "media_count", "biography", "website"]
PROFILE_REQUIRED = ("username",)
MEDIA_FIELDS = ["id", "caption", "media_type", "media_product_type", "permalink", "timestamp",
                "like_count", "comments_count", "is_comment_enabled", "shortcode",
                "thumbnail_url", "is_shared_to_feed"]
MEDIA_REQUIRED = ("id", "timestamp")
COMMENT_FIELDS = ["id", "text", "timestamp", "username", "like_count"]
COMMENT_REQUIRED = ("id", "text")

# Per-post metrics, from Meta's media insights reference. Stories are left out on
# purpose: their numbers live for 24 hours and need at least 5 viewers.
INSIGHT_METRICS = {
    "REELS": ["views", "reach", "likes", "comments", "shares", "saved", "total_interactions",
              "ig_reels_avg_watch_time", "reels_skip_rate", "reposts"],
    "FEED": ["views", "reach", "likes", "comments", "shares", "saved", "total_interactions",
             "follows", "profile_visits", "reposts"],
}

HINTS = {
    "token": ("The token is missing, expired or revoked. Generate a new one in the Meta app "
              "dashboard (Instagram > API setup with Instagram business login > Generate token), "
              f"put it in {TOKEN_ENV} and start a new session. See instagram-agent-skill/CONNECT.md."),
    "permission": ("The token does not allow this call. Insights need instagram_business_manage_insights; "
                   "comments need instagram_business_manage_comments. Generate a new token that "
                   "includes it, or paste the data instead."),
    "rate": "Meta's rate limit was hit. Wait a while, then retry with a smaller --limit.",
    "network": "Could not reach graph.instagram.com. Check the environment's network access.",
    "param": "Meta rejected a parameter (error 100). Run `doctor` to see what this token can read.",
}

_CALLS = 0
_API_VERSION = DEFAULT_VERSION


class ApiError(Exception):
    def __init__(self, message, kind="api", code=None, subcode=None, status=None):
        super().__init__(message)
        self.message = message
        self.kind = kind
        self.code = code
        self.subcode = subcode
        self.status = status


# ---------------------------------------------------------------- secrets

def redact(text):
    """Remove the token (and anything shaped like one in a URL) from a string."""
    text = str(text)
    token = os.environ.get(TOKEN_ENV, "").strip()
    if len(token) >= 8:
        for variant in {token, urllib.parse.quote(token, safe=""), urllib.parse.quote_plus(token)}:
            text = text.replace(variant, "[token]")
    return re.sub(r"(access_token=)[^&\s\"']+", r"\1[token]", text)


def get_token():
    token = os.environ.get(TOKEN_ENV, "").strip()
    if not token:
        raise ApiError(f"{TOKEN_ENV} is not set.", kind="token")
    if re.search(r"\s", token):
        raise ApiError(f"{TOKEN_ENV} contains whitespace; it was probably pasted with a line break.",
                       kind="token")
    return token


# ---------------------------------------------------------------- http

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect: the token travels in the query string."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def resolve_base():
    base = os.environ.get("IG_API_BASE", DEFAULT_BASE).rstrip("/")
    if base == DEFAULT_BASE:
        return base
    parsed = urllib.parse.urlparse(base)
    if parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost", "::1"):
        return base                      # a local stand-in server, for tests
    raise SystemExit("igapi: IG_API_BASE may only be https://graph.instagram.com or a loopback "
                     "address. Refusing to send the token anywhere else.")


def _classify(status, code, message, etype):
    msg = (message or "").lower()
    if status == 429 or code in (4, 17, 32, 613) or (isinstance(code, int) and 80000 <= code < 80100):
        return "rate"
    if code in (190, 102) or (etype == "OAuthException" and "access token" in msg and code != 10):
        return "token"
    if code == 10 or (isinstance(code, int) and 200 <= code < 300) or "permission" in msg:
        return "permission"
    if code == 100:
        return "param"
    if status and status >= 500 or code == 2:
        return "server"
    return "api"


def _error_from(body, status):
    try:
        err = json.loads(body.decode("utf-8", "replace")).get("error", {})
        if not isinstance(err, dict):
            err = {}
    except (ValueError, AttributeError):
        err = {}
    message = err.get("message") or f"HTTP {status}"
    code, sub = err.get("code"), err.get("error_subcode")
    return ApiError(redact(message), _classify(status, code, message, err.get("type")), code, sub, status)


def call(path, params=None, version=None, timeout=25):
    """One GET against the API. Returns the parsed JSON object."""
    global _CALLS
    token = get_token()
    if _CALLS >= MAX_CALLS:
        raise ApiError(f"stopped after {MAX_CALLS} API calls in one run", kind="rate")
    _CALLS += 1
    ver = _API_VERSION if version is None else version
    base = resolve_base()
    url = f"{base}/{ver}/{path.lstrip('/')}" if ver else f"{base}/{path.lstrip('/')}"
    query = dict(params or {})
    query["access_token"] = token
    request = urllib.request.Request(url + "?" + urllib.parse.urlencode(query), method="GET",
                                     headers={"Accept": "application/json", "User-Agent": "ig-connect/1.0"})
    opener = urllib.request.build_opener(_NoRedirect())
    for attempt in range(3):
        try:
            with opener.open(request, timeout=timeout) as resp:
                body = resp.read(MAX_BYTES + 1)
        except urllib.error.HTTPError as err:
            try:
                raw = err.read(MAX_BYTES)
            except OSError:
                raw = b""
            failure = _error_from(raw, err.code)
            if failure.kind == "server" and attempt < 2:
                _pause(1.5 * (attempt + 1))
                continue
            raise failure
        except (urllib.error.URLError, OSError) as err:
            if attempt < 2:
                _pause(1.5 * (attempt + 1))
                continue
            raise ApiError("network error: " + redact(getattr(err, "reason", err)), kind="network")
        if len(body) > MAX_BYTES:
            raise ApiError("response larger than the safety cap", kind="api")
        try:
            data = json.loads(body.decode("utf-8"))
        except ValueError:
            raise ApiError("Meta returned something that is not JSON", kind="api")
        if isinstance(data, dict) and isinstance(data.get("error"), dict):
            raise _error_from(json.dumps(data).encode(), 200)
        return data
    raise ApiError("network error", kind="network")


def _pause(seconds):
    if not os.environ.get("IG_NO_SLEEP"):
        time.sleep(seconds)


# ---------------------------------------------------------------- field fallback

def _blame(message, fields, required):
    """Which optional fields does an error message point at?"""
    named = [f for f in re.findall(r"\(([A-Za-z_]+)\)", message) if f in fields]
    if not named:
        named = [f for f in fields if re.search(r"\b" + re.escape(f) + r"\b", message)]
    return [f for f in named if f not in required]


def _field_ok(path, field, base):
    probe = dict(base, fields=field)
    if "limit" in probe:
        probe["limit"] = 1
    try:
        call(path, probe)
        return True
    except ApiError as err:
        if err.kind == "param":
            return False
        raise


def fetch_with_fields(path, fields, params=None, required=()):
    """GET with ?fields=..., dropping any optional field Meta rejects.

    Returns (response, dropped_fields). Only a parameter error (code 100) drops a
    field. Token, permission and rate problems are raised untouched.
    """
    fields = list(fields)
    dropped = []
    base = dict(params or {})
    for _ in range(len(fields) + 2):
        try:
            return call(path, dict(base, fields=",".join(fields))), dropped
        except ApiError as err:
            if err.kind != "param":
                raise
            bad = _blame(err.message, fields, required)
            if not bad:
                bad = [f for f in fields if f not in required and not _field_ok(path, f, base)]
            if not bad:
                raise
            for field in bad:
                fields.remove(field)
                dropped.append(field)
    raise ApiError("could not find a field list Meta accepts", kind="param")


# ---------------------------------------------------------------- data

def unwrap(resp):
    """/me answers with a flat object in some versions and {"data": [object]} in others."""
    if isinstance(resp, dict) and isinstance(resp.get("data"), list) and len(resp["data"]) == 1 \
            and isinstance(resp["data"][0], dict):
        return resp["data"][0]
    return resp if isinstance(resp, dict) else {}


def fetch_profile():
    resp, dropped = fetch_with_fields("me", PROFILE_FIELDS, required=PROFILE_REQUIRED)
    return unwrap(resp), dropped


def parse_ts(value):
    if not value:
        return None
    text = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", str(value).strip()).replace("Z", "+00:00")
    try:
        when = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=dt.timezone.utc)


def product_type(media):
    kind = (media.get("media_product_type") or "").upper()
    if kind in ("REELS", "FEED", "STORY", "AD"):
        return kind
    link = media.get("permalink") or ""
    return "REELS" if "/reel/" in link or "/reels/" in link else "FEED"


def _fresh(page, known):
    """Items of a page whose id has not come up yet, so a repeated page adds nothing."""
    out = []
    for item in page:
        key = item.get("id")
        if key is not None:
            if key in known:
                continue
            known.add(key)
        out.append(item)
    return out


def fetch_media(limit, since=None, kind="all"):
    fields = list(MEDIA_FIELDS)
    dropped, items, cursor, seen, ids = [], [], None, set(), set()
    for _ in range(40):
        want = min(50, max(1, limit - len(items)))
        params = {"limit": want}
        if cursor:
            params["after"] = cursor
        resp, gone = fetch_with_fields("me/media", fields, params, MEDIA_REQUIRED)
        for field in gone:
            if field in fields:
                fields.remove(field)
            if field not in dropped:
                dropped.append(field)
        page = _fresh(resp.get("data") or [], ids)
        stop = False
        for media in page:
            when = parse_ts(media.get("timestamp"))
            if since and when and when < since:
                stop = True
                break
            if kind != "all" and product_type(media).lower() != kind:
                continue
            items.append(media)
            if len(items) >= limit:
                stop = True
                break
        cursor = ((resp.get("paging") or {}).get("cursors") or {}).get("after")
        # Some responses carry no "next" link even when more posts exist, so follow the
        # cursor until a page comes back empty. The cost is one extra call at the end.
        if stop or not page or not cursor or cursor in seen:
            break
        seen.add(cursor)
    return items, dropped


def _insight_values(resp):
    out = {}
    for item in resp.get("data") or []:
        name, values = item.get("name"), item.get("values") or []
        value = values[0].get("value") if values and isinstance(values[0], dict) else None
        if value is None and isinstance(item.get("total_value"), dict):
            value = item["total_value"].get("value")
        if name and isinstance(value, (int, float)) and not isinstance(value, bool):
            out[name] = value
    return out


def media_insights(media_id, kind, unsupported):
    """Insight numbers for one post. Returns (metrics, note).

    A batch call fails as a whole if any metric is unsupported, so on a parameter
    error the metrics are asked one by one. A metric is remembered as unsupported
    only when the same post answered some other metric, which rules out the post
    simply having no data (too new, or from before the account was professional).
    """
    wanted = [m for m in INSIGHT_METRICS[kind] if m not in unsupported]
    first = None
    try:
        return _insight_values(call(f"{media_id}/insights", {"metric": ",".join(wanted)})), None
    except ApiError as err:
        if err.kind != "param":
            raise
        first = err
    got, failed = {}, []
    for metric in wanted:
        try:
            got.update(_insight_values(call(f"{media_id}/insights", {"metric": metric})))
        except ApiError as err:
            if err.kind != "param":
                raise
            failed.append(metric)
    if got:
        unsupported.update(failed)
        return got, None
    return {}, "no insight data: " + shorten(first.message, 90)


def ratio(a, b):
    ok = lambda x: isinstance(x, (int, float)) and not isinstance(x, bool)
    return round(a / b, 4) if ok(a) and ok(b) and b else None


def build_rows(items):
    unsupported = {"REELS": set(), "FEED": set()}
    rows = []
    for media in items:
        kind = product_type(media)
        if kind not in INSIGHT_METRICS:
            continue
        metrics, note = media_insights(media["id"], kind, unsupported[kind])
        rows.append({
            "id": media.get("id"), "type": kind, "media_type": media.get("media_type"),
            "timestamp": media.get("timestamp"), "permalink": media.get("permalink"),
            "caption": media.get("caption"), "like_count": media.get("like_count"),
            "comments_count": media.get("comments_count"),
            "metrics": metrics, "note": note,
        })
    return rows, {k: sorted(v) for k, v in unsupported.items() if v}


def derive(rows):
    """Add the ratios ig-audit ranks on. The baseline is the account's own median."""
    def series(name):
        return [r["metrics"][name] for r in rows if name in r["metrics"]]

    baseline = "views" if len(series("views")) >= max(3, 0.6 * len(rows)) else "reach"
    values = series(baseline)
    median = statistics.median(values) if values else None
    for row in rows:
        m = row["metrics"]
        row["outlier"] = round(m[baseline] / median, 2) if baseline in m and median else None
        row["sends_per_reach"] = ratio(m.get("shares"), m.get("reach"))
        row["saves_per_reach"] = ratio(m.get("saved"), m.get("reach"))
        row["follows_per_reach"] = ratio(m.get("follows"), m.get("reach"))
    rows.sort(key=lambda r: (r["outlier"] is None, -(r["outlier"] or 0)))
    return baseline, median


def fetch_comments(media_id, limit):
    fields = list(COMMENT_FIELDS)
    dropped, items, cursor, seen, ids = [], [], None, set(), set()
    for _ in range(20):
        want = min(50, max(1, limit - len(items)))
        params = {"limit": want}
        if cursor:
            params["after"] = cursor
        resp, gone = fetch_with_fields(f"{media_id}/comments", fields, params, COMMENT_REQUIRED)
        for field in gone:
            if field in fields:
                fields.remove(field)
            if field not in dropped:
                dropped.append(field)
        page = _fresh(resp.get("data") or [], ids)
        items.extend(page[:limit - len(items)])
        cursor = ((resp.get("paging") or {}).get("cursors") or {}).get("after")
        if len(items) >= limit or not page or not cursor or cursor in seen:
            break
        seen.add(cursor)
    return items, dropped


# ---------------------------------------------------------------- rendering

def shorten(text, n):
    flat = re.sub(r"\s+", " ", text or "").strip()
    return flat if len(flat) <= n else flat[:n - 3] + "..."


def num(x, places=0):
    if not isinstance(x, (int, float)) or isinstance(x, bool):
        return "-"
    return f"{x:,.{places}f}" if places else f"{x:,.0f}"


def pct(x):
    return "-" if x is None else f"{x * 100:.2f}%"


def day(ts):
    when = parse_ts(ts)
    return when.strftime("%Y-%m-%d") if when else "-"


def render_me(p):
    prof = p["profile"]
    lines = ["", "PROFILE", "=" * 62]
    for key in PROFILE_FIELDS:
        if key in prof:
            val = prof[key]
            lines.append(f"  {key:<20} {num(val) if isinstance(val, int) else shorten(str(val), 80)}")
    if p["unavailable_fields"]:
        lines.append(f"\n  Not readable with this token or API: {', '.join(p['unavailable_fields'])}")
    return lines


def render_media(p):
    lines = ["", f"POSTS  ·  {p['count']} found", "=" * 78]
    for m in p["media"]:
        lines.append(f"  {day(m.get('timestamp'))}  {product_type(m):<5}  likes {num(m.get('like_count')):>7}  "
                     f"comments {num(m.get('comments_count')):>5}  {shorten(m.get('caption'), 34)}")
        lines.append(f"      {m.get('id')}  {m.get('permalink') or ''}")
    if p["unavailable_fields"]:
        lines.append(f"\n  Not readable with this token or API: {', '.join(p['unavailable_fields'])}")
    return lines


def render_insights(p):
    head = (f"INSIGHTS  ·  {p['count']} posts  ·  baseline: median {p['baseline']} "
            f"{num(p['median'])} (the account's own, not a benchmark)")
    lines = ["", head, "=" * 100,
             "  outlier  type   date        views    reach  sends/reach  saves/reach  follows/reach  caption"]
    for r in p["posts"]:
        m = r["metrics"]
        out = f"{r['outlier']:.1f}x" if r["outlier"] is not None else "-"
        lines.append(f"  {out:>7}  {r['type']:<5}  {day(r['timestamp'])}  {num(m.get('views')):>7}  "
                     f"{num(m.get('reach')):>7}  {pct(r['sends_per_reach']):>11}  {pct(r['saves_per_reach']):>11}  "
                     f"{pct(r['follows_per_reach']):>13}  {shorten(r['caption'], 28)}")
        if r["note"]:
            lines.append(f"           ^ {r['note']}")
    lines.append("-" * 100)
    for kind, gone in p["unavailable_metrics"].items():
        lines.append(f"  Not available for {kind}: {', '.join(gone)}")
    lines += [
        "  The API does not return hold at 3s, the retention graph, or the non-follower share of reach per post.",
        "  reels_skip_rate, where present, is Meta's estimate of views skipped in the first 3 seconds;",
        "  its unit is not stated in the docs, so check it against the app before using it as hold at 3s.",
        "  Insight numbers can lag up to 48 hours, so the newest posts may be incomplete.",
    ]
    return lines


def render_comments(p):
    lines = ["", f"COMMENTS  ·  {p['count']} on post {p['media_id']}", "=" * 78]
    for c in p["comments"]:
        who = c.get("username") or "?"
        lines.append(f"  @{who}  {day(c.get('timestamp'))}  likes {num(c.get('like_count'))}")
        lines.append(f"    {shorten(c.get('text'), 200)}")
    if p["unavailable_fields"]:
        lines.append(f"\n  Not readable with this token or API: {', '.join(p['unavailable_fields'])}")
    return lines


# ---------------------------------------------------------------- output

def inside_git_repo(path):
    here = os.path.dirname(os.path.realpath(os.path.abspath(path))) or "."
    while True:
        if os.path.exists(os.path.join(here, ".git")):
            return True
        parent = os.path.dirname(here)
        if parent == here:
            return False
        here = parent


def save(path, payload, allow_in_repo=False):
    target = os.path.expanduser(path)
    if inside_git_repo(target) and not allow_in_repo:
        raise SystemExit("igapi: refusing to save inside a git repository. This data is private "
                         "(analytics and other people's comments) and a repository can be public. "
                         "Use a path such as ~/.claude/instagram/audit.json.")
    os.makedirs(os.path.dirname(os.path.abspath(target)), mode=0o700, exist_ok=True)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
    print(f"wrote {target}", file=sys.stderr)


def emit(args, payload, renderer):
    if args.out:
        save(args.out, payload, args.allow_in_repo)
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print("\n".join(renderer(payload)) + "\n")


# ---------------------------------------------------------------- commands

def cmd_me(args):
    prof, dropped = fetch_profile()
    emit(args, {"profile": prof, "unavailable_fields": dropped}, render_me)
    return 0


def cmd_media(args):
    items, dropped = fetch_media(args.limit, args.since_dt, args.type)
    emit(args, {"count": len(items), "unavailable_fields": dropped, "media": items}, render_media)
    return 0


def cmd_insights(args):
    items, dropped = fetch_media(args.limit, args.since_dt, args.type)
    rows, unavailable = build_rows(items)
    baseline, median = derive(rows)
    payload = {"count": len(rows), "baseline": baseline, "median": median,
               "unavailable_fields": dropped, "unavailable_metrics": unavailable, "posts": rows}
    emit(args, payload, render_insights)
    return 0


def cmd_comments(args):
    if not re.fullmatch(r"\d+", args.media_id):
        print("igapi: MEDIA_ID must be the numeric post id (see `media`).", file=sys.stderr)
        return EXIT["usage"]
    items, dropped = fetch_comments(args.media_id, args.limit)
    emit(args, {"media_id": args.media_id, "count": len(items), "unavailable_fields": dropped,
                "comments": items}, render_comments)
    return 0


def cmd_refresh(args):
    token = get_token()
    resp = call("refresh_access_token", {"grant_type": "ig_refresh_token"}, version="")
    new = resp.get("access_token")
    seconds = resp.get("expires_in")
    days = round(seconds / 86400, 1) if isinstance(seconds, (int, float)) else None
    changed = bool(new) and new != token
    payload = {"expires_in_days": days, "token_changed": changed}
    if changed and args.print_new_token:
        payload["new_token"] = new
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0
    lines = ["", "TOKEN REFRESH", "=" * 62,
             f"  new lifetime: {days} days" if days is not None else "  new lifetime: not reported"]
    if not changed:
        lines.append("  Meta kept the same token string, so IG_ACCESS_TOKEN stays valid. "
                     "Set IG_TOKEN_ISSUED to today's date.")
    elif args.print_new_token:
        lines += ["  Meta issued a NEW token. Copy it into IG_ACCESS_TOKEN now:", f"  {new}",
                  "  It was printed because you asked; treat this conversation as sensitive."]
    else:
        lines += ["  Meta issued a NEW token and it was NOT printed. The current token may stay valid "
                  "until its original expiry,",
                  "  but to keep going, generate a fresh token in the app dashboard, or rerun with "
                  "--print-new-token."]
    print("\n".join(lines) + "\n")
    return 0


def cmd_doctor(args):
    checks = []
    failed = []                                   # error kinds of the failed checks, in order

    def add(status, name, detail, kind=None):
        checks.append((status, name, detail))
        if status == "FAIL":
            failed.append(kind or "error")

    def finish():
        if failed:
            verdict = "FIX"
        elif all(s in ("PASS", "INFO") for s, _, _ in checks):
            verdict = "READY"
        else:
            verdict = "PARTIAL"
        lines = ["", "IG CONNECT DOCTOR", "=" * 62]
        lines += [f"  {s:<5} {n:<10} {d}" for s, n, d in checks]
        lines += ["-" * 62, f"  VERDICT  {verdict}", ""]
        print("\n".join(lines))
        return EXIT.get(failed[0], 1) if failed else 0

    try:
        token = get_token()
    except ApiError as err:
        add("FAIL", "TOKEN", err.message + " See instagram-agent-skill/CONNECT.md.", "token")
        return finish()
    add("PASS", "TOKEN", f"{TOKEN_ENV} is set ({len(token)} characters)")
    add("INFO", "API", f"{resolve_base().split('//', 1)[1]} {_API_VERSION}")

    issued = os.environ.get("IG_TOKEN_ISSUED", "").strip()
    if issued:
        try:
            age = (dt.datetime.now(dt.timezone.utc).date() - dt.date.fromisoformat(issued)).days
            left = TOKEN_LIFETIME_DAYS - age
            status = "PASS" if left > 14 else ("WARN" if left > 0 else "FAIL")
            add(status, "EXPIRY", f"issued {issued}: about {left} days left" +
                ("" if left > 14 else ". Run `refresh` now (the token must be at least 24 hours old)"))
        except ValueError:
            add("WARN", "EXPIRY", "IG_TOKEN_ISSUED is not a YYYY-MM-DD date")
    else:
        add("INFO", "EXPIRY", "IG_TOKEN_ISSUED is not set. Tokens last 60 days; set it to the day you "
                              "generated yours to get warnings")

    try:
        prof, dropped = fetch_profile()
        followers = prof.get("followers_count")
        add("PASS", "ACCOUNT", f"@{prof.get('username')}  {prof.get('account_type', '')}  "
                               f"{num(followers)} followers  {num(prof.get('media_count'))} posts")
        if dropped:
            add("WARN", "PROFILE", "not readable with this token or API: " + ", ".join(dropped))
        items, gone = fetch_media(5)
        if not items:
            add("WARN", "MEDIA", "no posts returned")
        else:
            add("PASS", "MEDIA", f"posts readable ({len(items)} fetched)" +
                (f"; not readable: {', '.join(gone)}" if gone else ""))
    except ApiError as err:
        add("FAIL", "ACCOUNT", f"{err.message} ({err.kind})", err.kind)
        return finish()

    eligible = [m for m in items if product_type(m) in INSIGHT_METRICS]
    if not eligible:
        add("WARN", "INSIGHTS", "no feed or reel post to test on")
    else:
        try:
            result = None
            for media in eligible[:3]:
                kind = product_type(media)
                metrics, note = media_insights(media["id"], kind, set())
                if metrics:
                    result = (kind, sorted(metrics))
                    break
            if result:
                add("PASS", "INSIGHTS", f"readable on a {result[0]} post: " + ", ".join(result[1]))
            else:
                add("WARN", "INSIGHTS", "no data on the newest posts (numbers can lag 48 hours)")
        except ApiError as err:
            add("FAIL" if err.kind in ("permission", "token") else "WARN", "INSIGHTS",
                f"{err.message} ({err.kind})", err.kind)
            if err.kind == "permission":
                add("INFO", "FIX", "generate a token that includes instagram_business_manage_insights")

    if args.comments and items:
        target = next((m for m in items if (m.get("comments_count") or 0) > 0), items[0])
        try:
            fetch_comments(target["id"], 1)
            add("PASS", "COMMENTS", "readable. Note this permission also allows replying, hiding and "
                                    "deleting; this script never does")
        except ApiError as err:
            add("FAIL" if err.kind in ("permission", "token") else "WARN", "COMMENTS",
                f"{err.message} ({err.kind})", err.kind)
    elif not args.comments:
        add("INFO", "COMMENTS", "not tested. Run `doctor --comments` if you added that permission")
    return finish()


# ---------------------------------------------------------------- main

def build_parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="print JSON instead of a table")
    common.add_argument("--out", help="also save the JSON here (refused inside a git repository)")
    common.add_argument("--allow-in-repo", action="store_true",
                        help="override the git-repository guard for --out (not recommended)")
    common.add_argument("--api-version", help=f"Graph API version (default {DEFAULT_VERSION} or $IG_API_VERSION)")

    ap = argparse.ArgumentParser(prog="igapi.py", description="Read your own Instagram account (read-only).")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("doctor", parents=[common], help="check the token, the account and what it can read")
    p.add_argument("--comments", action="store_true", help="also test reading comments")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("me", parents=[common], help="profile fields")
    p.set_defaults(func=cmd_me)

    for name, func, helptext in (("media", cmd_media, "recent posts"),
                                 ("insights", cmd_insights, "per-post insights and the ratios ig-audit uses")):
        p = sub.add_parser(name, parents=[common], help=helptext)
        p.add_argument("--limit", type=int, default=25, help="how many posts (default 25, max 200)")
        p.add_argument("--since", help="only posts from this date on, YYYY-MM-DD (UTC)")
        p.add_argument("--type", choices=["all", "feed", "reels"], default="all")
        p.set_defaults(func=func)

    p = sub.add_parser("comments", parents=[common], help="comments on one post")
    p.add_argument("media_id")
    p.add_argument("--limit", type=int, default=50, help="how many comments (default 50, max 500)")
    p.set_defaults(func=cmd_comments)

    p = sub.add_parser("refresh", parents=[common], help="extend the token's 60-day life")
    p.add_argument("--print-new-token", action="store_true",
                   help="if Meta issues a different token, print it (it will appear in the conversation)")
    p.set_defaults(func=cmd_refresh)
    return ap


def main(argv=None):
    global _API_VERSION
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass
    args = build_parser().parse_args(argv)

    version = args.api_version or os.environ.get("IG_API_VERSION") or DEFAULT_VERSION
    if not re.fullmatch(r"v\d+\.\d+", version):
        print("igapi: the API version must look like v26.0", file=sys.stderr)
        return EXIT["usage"]
    _API_VERSION = version

    args.since_dt = None
    if getattr(args, "since", None):
        try:
            args.since_dt = dt.datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc)
        except ValueError:
            print("igapi: --since must be YYYY-MM-DD", file=sys.stderr)
            return EXIT["usage"]
    if hasattr(args, "limit"):
        args.limit = max(1, min(args.limit, 500 if args.cmd == "comments" else 200))

    try:
        return args.func(args)
    except ApiError as err:
        print(f"igapi: {err.message}", file=sys.stderr)
        if err.kind in HINTS:
            print(f"       {HINTS[err.kind]}", file=sys.stderr)
        return EXIT.get(err.kind, 1)
    except KeyboardInterrupt:
        return 130
    except SystemExit:
        raise
    except Exception as err:                       # never let a traceback carry the token
        print(redact(f"igapi: unexpected error: {type(err).__name__}: {err}"), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
