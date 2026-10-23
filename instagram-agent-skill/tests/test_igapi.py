#!/usr/bin/env python3
"""
Tests for ig-connect/igapi.py against a local stand-in for graph.instagram.com.

These prove the client's own behaviour: pagination, dropping fields and metrics
Meta rejects, error mapping, that the token never reaches the output, that only
GET requests are made, and that --out refuses to write inside a git repository.

They do NOT prove the script works against Meta's real API: the stand-in is
written from Meta's documentation, not captured from a live account. The first
real run is `igapi.py doctor` with a real token.

Run:  python3 -I -B -m unittest discover -s instagram-agent-skill/tests -v
"""

import contextlib
import datetime as dt
import http.server
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
IGAPI = os.path.normpath(os.path.join(HERE, "..", "..", ".claude", "skills", "ig-connect", "igapi.py"))
TOKEN = "IGAAFAKE_TEST_TOKEN_0123456789abcdefghij"
NEW_TOKEN = "IGAANEWER_TEST_TOKEN_9876543210zyxwvuts"

REELS_OK = {"views", "reach", "likes", "comments", "shares", "saved", "total_interactions",
            "ig_reels_avg_watch_time", "reels_skip_rate"}
FEED_OK = {"views", "reach", "likes", "comments", "shares", "saved", "total_interactions",
           "follows", "profile_visits"}


def make_media(n):
    """Newest first. Even index = Reel, odd = feed image. Views are (i+1)*100."""
    items = []
    for i in range(n):
        reel = i % 2 == 0
        item = {
            "id": str(1000 + i), "caption": f"post {i}",
            "media_type": "VIDEO" if reel else "IMAGE",
            "media_product_type": "REELS" if reel else "FEED",
            "permalink": f"https://www.instagram.com/{'reel' if reel else 'p'}/ABC{i}/",
            "timestamp": f"2026-10-{20 - i:02d}T12:00:00+0000",
            "like_count": 10 + i, "comments_count": i, "is_comment_enabled": True,
            "shortcode": f"ABC{i}", "is_shared_to_feed": True,
        }
        if reel:
            item["thumbnail_url"] = "https://example.invalid/t.jpg"
        items.append(item)
    return items


def metric_value(media_id, metric):
    i = int(media_id) - 1000
    views = (i + 1) * 100
    return {"views": views, "reach": views // 2, "likes": 10 + i, "comments": i, "shares": i + 1,
            "saved": 2 * (i + 1), "total_interactions": 20 + i, "follows": i, "profile_visits": 3 * i,
            "ig_reels_avg_watch_time": 7000, "reels_skip_rate": 0.4}[metric]


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, status, obj):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _err(self, status, code, message, etype="OAuthException", sub=None):
        err = {"message": message, "type": etype, "code": code, "fbtrace_id": "TRACE"}
        if sub:
            err["error_subcode"] = sub
        self._send(status, {"error": err})

    def _refuse(self):
        self.server.log.append((self.command, self.path, {}))
        self._send(405, {"error": {"message": "method not allowed", "code": 1}})

    do_POST = do_PUT = do_DELETE = do_PATCH = _refuse

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
        self.server.log.append(("GET", url.path, q))
        st = self.server.state
        if st.get("echo_token"):
            return self._err(400, 100, f"echo access_token={q.get('access_token')} and {q.get('access_token')}")
        if q.get("access_token") != TOKEN:
            return self._err(400, 190, "Invalid OAuth access token - Cannot parse access token")
        if st.get("server_error"):
            return self._send(500, {"error": {"message": "internal", "code": 2}})
        if st.get("rate_limit"):
            return self._err(400, 4, "(#4) Application request limit reached")
        if url.path == "/refresh_access_token":
            return self._send(200, {"access_token": TOKEN if st.get("refresh_same", True) else NEW_TOKEN,
                                    "token_type": "bearer", "expires_in": 5183944})
        m = re.fullmatch(r"/v26\.0/(.+)", url.path)
        if not m:
            return self._err(404, 100, "unknown path")
        rest = m.group(1)
        fields = [f for f in q.get("fields", "").split(",") if f]
        if rest == "me":
            profile = {"user_id": "17841400000000000", "username": "demo", "name": "Demo Account",
                       "account_type": "BUSINESS", "followers_count": 1234, "follows_count": 10,
                       "media_count": 7, "biography": "bio text", "website": "https://example.invalid"}
            for f in fields:
                if f in st.get("reject_profile", ()):
                    return self._err(400, 100, f"(#100) Tried accessing nonexisting field ({f}) on node type (IGUser)")
            data = {f: profile[f] for f in fields if f in profile}
            return self._send(200, {"data": [data]} if st.get("me_shape") == "data" else data)
        if rest == "me/media":
            for f in fields:
                if f in st.get("reject_media", ()):
                    return self._err(400, 100, f"(#100) Tried accessing nonexisting field ({f}) on node type (IGUser)")
            items = st["media"]
            start = int(q["after"][1:]) if q.get("after") and not st.get("repeat_pages") else 0
            size = min(int(q.get("limit", 25)), st.get("page_cap", 25))
            page = items[start:start + size]
            data = [{f: it[f] for f in fields if f in it} for it in page]
            end = start + len(page)
            paging = {"cursors": {"before": f"c{start}", "after": f"c{end}"}}
            if end < len(items) and not st.get("omit_next"):
                paging["next"] = "http://example.invalid/next"
            return self._send(200, {"data": data, "paging": paging})
        m = re.fullmatch(r"(\d+)/insights", rest)
        if m:
            media_id = m.group(1)
            if st.get("no_data_ids") and media_id in st["no_data_ids"]:
                return self._err(400, 100, "(#100) Media posted before the account became professional",
                                 etype="OAuthException", sub=2108006)
            item = next((x for x in st["media"] if x["id"] == media_id), None)
            ok = REELS_OK if item and item["media_product_type"] == "REELS" else FEED_OK
            metrics = [x for x in q.get("metric", "").split(",") if x]
            bad = [x for x in metrics if x not in ok]
            if bad:
                return self._err(400, 100, f"(#100) metric {bad[0]} is not supported for this media")
            return self._send(200, {"data": [
                {"name": x, "period": "lifetime", "values": [{"value": metric_value(media_id, x)}],
                 "title": x, "id": f"{media_id}/insights/{x}/lifetime"} for x in metrics]})
        m = re.fullmatch(r"(\d+)/comments", rest)
        if m:
            if st.get("comments_forbidden"):
                return self._err(400, 10, "(#10) Application does not have permission for this action")
            comments = [{"id": f"9{i}", "text": f"comment {i}", "timestamp": "2026-10-19T10:00:00+0000",
                         "username": f"user{i}", "like_count": i} for i in range(3)]
            if q.get("after"):
                comments = []                      # the stand-in has one page only
            return self._send(200, {"data": [{f: c[f] for f in fields if f in c} for c in comments],
                                    "paging": {"cursors": {"before": "a", "after": "b"}}})
        return self._err(400, 100, "Unsupported get request")


class Fake(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, **state):
        super().__init__(("127.0.0.1", 0), Handler)
        self.log = []
        self.state = {"media": make_media(6)}
        self.state.update(state)

    @property
    def base(self):
        return f"http://127.0.0.1:{self.server_address[1]}"


@contextlib.contextmanager
def serve(**state):
    server = Fake(**state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()


def run(server, *args, token=TOKEN, env_extra=None, base=None):
    env = {k: v for k, v in os.environ.items()
           if k.lower() not in ("http_proxy", "https_proxy", "all_proxy", "no_proxy")}
    env.update({"IG_ACCESS_TOKEN": token, "IG_API_BASE": base or server.base, "IG_NO_SLEEP": "1",
                "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"})
    env.update(env_extra or {})
    if token is None:
        env.pop("IG_ACCESS_TOKEN")
    return subprocess.run([sys.executable, "-I", "-B", IGAPI, *args], env=env, capture_output=True,
                          text=True, timeout=60)


def insight_calls(server):
    return [e for e in server.log if e[1].endswith("/insights")]


class Profile(unittest.TestCase):
    def test_flat_and_data_shapes(self):
        for shape in ("flat", "data"):
            with serve(me_shape=shape) as s:
                out = run(s, "me", "--json")
                self.assertEqual(out.returncode, 0, out.stderr)
                self.assertEqual(json.loads(out.stdout)["profile"]["username"], "demo")

    def test_drops_a_field_meta_rejects(self):
        with serve(reject_profile={"biography", "website"}) as s:
            out = run(s, "me", "--json")
            self.assertEqual(out.returncode, 0, out.stderr)
            payload = json.loads(out.stdout)
            self.assertEqual(sorted(payload["unavailable_fields"]), ["biography", "website"])
            self.assertEqual(payload["profile"]["followers_count"], 1234)
            self.assertIn("Not readable", run(s, "me").stdout)


class Media(unittest.TestCase):
    def test_pagination_and_limit(self):
        with serve(page_cap=3, media=make_media(7)) as s:
            out = run(s, "media", "--limit", "5", "--json")
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertEqual([m["id"] for m in json.loads(out.stdout)["media"]],
                             ["1000", "1001", "1002", "1003", "1004"])

    def test_pagination_without_a_next_link(self):
        with serve(page_cap=3, omit_next=True, media=make_media(7)) as s:
            out = run(s, "media", "--limit", "5", "--json")
            self.assertEqual(len(json.loads(out.stdout)["media"]), 5)

    def test_since_and_type_filters(self):
        with serve(media=make_media(7)) as s:
            since = json.loads(run(s, "media", "--since", "2026-10-17", "--json").stdout)
            self.assertEqual([m["id"] for m in since["media"]], ["1000", "1001", "1002", "1003"])
            reels = json.loads(run(s, "media", "--type", "reels", "--limit", "3", "--json").stdout)
            self.assertEqual([m["id"] for m in reels["media"]], ["1000", "1002", "1004"])

    def test_reel_detected_from_permalink_when_the_field_is_rejected(self):
        with serve(reject_media={"media_product_type"}) as s:
            out = run(s, "insights", "--json")
            self.assertEqual(out.returncode, 0, out.stderr)
            payload = json.loads(out.stdout)
            self.assertIn("media_product_type", payload["unavailable_fields"])
            self.assertEqual({p["id"]: p["type"] for p in payload["posts"]}["1000"], "REELS")
            self.assertIn("reels_skip_rate", {p["id"]: p for p in payload["posts"]}["1000"]["metrics"])


class Insights(unittest.TestCase):
    def test_metric_discovery_ratios_and_order(self):
        with serve() as s:
            out = run(s, "insights", "--json")
            self.assertEqual(out.returncode, 0, out.stderr)
            payload = json.loads(out.stdout)
            self.assertEqual(payload["baseline"], "views")
            self.assertEqual(payload["median"], 350)
            self.assertEqual(payload["unavailable_metrics"], {"REELS": ["reposts"], "FEED": ["reposts"]})
            posts = payload["posts"]
            self.assertEqual(posts[0]["id"], "1005")                       # 600 views, the biggest outlier
            self.assertEqual(posts[0]["outlier"], 1.71)
            self.assertEqual([p["id"] for p in posts], sorted((p["id"] for p in posts), reverse=True))
            reel = next(p for p in posts if p["id"] == "1000")
            self.assertEqual(reel["sends_per_reach"], round(1 / 50, 4))    # shares 1 / reach 50
            self.assertEqual(reel["saves_per_reach"], round(2 / 50, 4))
            self.assertIsNone(reel["follows_per_reach"])                   # reels have no follows metric
            feed = next(p for p in posts if p["id"] == "1005")
            self.assertEqual(feed["follows_per_reach"], round(5 / 300, 4))
            # After discovery, a post costs one call, and the rejected metric is no longer asked for.
            late = [e for e in insight_calls(s) if e[1].endswith(("/1004/insights", "/1005/insights"))]
            self.assertTrue(late)
            self.assertTrue(all("reposts" not in e[2]["metric"] for e in late[-2:]))
            self.assertLessEqual(len(insight_calls(s)), 40)

    def test_a_post_without_data_does_not_poison_the_metric_cache(self):
        with serve(no_data_ids={"1000"}) as s:
            payload = json.loads(run(s, "insights", "--json").stdout)
            first = next(p for p in payload["posts"] if p["id"] == "1000")
            self.assertEqual(first["metrics"], {})
            self.assertIn("no insight data", first["note"])
            other = next(p for p in payload["posts"] if p["id"] == "1002")
            self.assertIn("views", other["metrics"])
            self.assertIn("ig_reels_avg_watch_time", other["metrics"])

    def test_table_output_mentions_the_limits_of_the_api(self):
        with serve() as s:
            text = run(s, "insights").stdout
            self.assertIn("INSIGHTS", text)
            self.assertIn("does not return hold at 3s", text)


class Comments(unittest.TestCase):
    def test_reads_comments(self):
        with serve() as s:
            out = run(s, "comments", "1000", "--json")
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertEqual(json.loads(out.stdout)["count"], 3)

    def test_missing_permission_is_reported_with_the_fix(self):
        with serve(comments_forbidden=True) as s:
            out = run(s, "comments", "1000")
            self.assertEqual(out.returncode, 4)
            self.assertIn("instagram_business_manage_comments", out.stderr)

    def test_a_repeated_page_adds_no_duplicates(self):
        with serve(repeat_pages=True, media=make_media(4)) as s:
            payload = json.loads(run(s, "media", "--limit", "10", "--json").stdout)
            ids = [m["id"] for m in payload["media"]]
            self.assertEqual(len(ids), len(set(ids)))

    def test_media_id_must_be_numeric(self):
        with serve() as s:
            out = run(s, "comments", "../me")
            self.assertEqual(out.returncode, 2)
            self.assertEqual(s.log, [])


class Errors(unittest.TestCase):
    def test_bad_token_exit_3_and_never_printed(self):
        with serve() as s:
            out = run(s, "me", token="IGAAWRONG_TOKEN_0123456789abcdef")
            self.assertEqual(out.returncode, 3)
            self.assertIn("expired or revoked", out.stderr)
            self.assertNotIn("IGAAWRONG_TOKEN_0123456789abcdef", out.stdout + out.stderr)

    def test_missing_token_exit_3(self):
        with serve() as s:
            out = run(s, "me", token=None)
            self.assertEqual(out.returncode, 3)
            self.assertEqual(s.log, [])

    def test_rate_limit_exit_5(self):
        with serve(rate_limit=True) as s:
            self.assertEqual(run(s, "media").returncode, 5)

    def test_server_error_exit_1_after_retries(self):
        with serve(server_error=True) as s:
            self.assertEqual(run(s, "me").returncode, 1)
            self.assertEqual(len(s.log), 3)

    def test_network_failure_exit_6(self):
        with serve() as s:
            self.assertEqual(run(s, "me", base="http://127.0.0.1:1").returncode, 6)

    def test_token_echoed_by_the_server_is_redacted(self):
        with serve(echo_token=True) as s:
            out = run(s, "me")
            self.assertNotIn(TOKEN, out.stdout + out.stderr)
            self.assertIn("[token]", out.stderr)

    def test_base_override_to_another_host_is_refused_before_any_request(self):
        with serve() as s:
            out = run(s, "me", base="https://evil.example")
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("Refusing to send the token", out.stderr)
            self.assertEqual(s.log, [])


class Safety(unittest.TestCase):
    def test_every_request_is_a_get_and_the_token_never_appears(self):
        with serve() as s:
            outputs = []
            for args in (("doctor", "--comments"), ("me",), ("media",), ("insights",),
                         ("comments", "1000"), ("refresh",), ("insights", "--json"), ("doctor",)):
                out = run(s, *args)
                outputs.append(out.stdout + out.stderr)
            self.assertTrue(s.log)
            self.assertEqual({entry[0] for entry in s.log}, {"GET"})
            self.assertFalse([o for o in outputs if TOKEN in o])

    def test_source_declares_only_get(self):
        with open(IGAPI, encoding="utf-8") as fh:
            source = fh.read()
        self.assertEqual(set(re.findall(r"method\s*=\s*[\"'](\w+)[\"']", source)), {"GET"})
        self.assertNotIn("add_header(\"Authorization\"", source)

    def test_out_is_refused_inside_a_git_repository(self):
        with serve() as s, tempfile.TemporaryDirectory() as tmp:
            repo = os.path.join(tmp, "repo")
            os.makedirs(os.path.join(repo, ".git"))
            blocked = run(s, "me", "--out", os.path.join(repo, "sub", "me.json"))
            self.assertNotEqual(blocked.returncode, 0)
            self.assertIn("refusing to save", blocked.stderr)
            self.assertFalse(os.path.exists(os.path.join(repo, "sub")))
            target = os.path.join(tmp, "private", "me.json")
            ok = run(s, "me", "--out", target)
            self.assertEqual(ok.returncode, 0, ok.stderr)
            with open(target, encoding="utf-8") as fh:
                saved = fh.read()
            self.assertEqual(json.loads(saved)["profile"]["username"], "demo")
            self.assertEqual(os.stat(target).st_mode & 0o777, 0o600)
            self.assertNotIn(TOKEN, saved)


class Refresh(unittest.TestCase):
    def test_same_token_keeps_working_and_nothing_is_printed(self):
        with serve(refresh_same=True) as s:
            out = run(s, "refresh")
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertIn("same token", out.stdout)
            payload = json.loads(run(s, "refresh", "--json").stdout)
            self.assertEqual(payload["expires_in_days"], 60.0)
            self.assertFalse(payload["token_changed"])
            self.assertNotIn(TOKEN, out.stdout + out.stderr)

    def test_new_token_is_only_printed_on_request(self):
        with serve(refresh_same=False) as s:
            quiet = run(s, "refresh")
            self.assertNotIn(NEW_TOKEN, quiet.stdout + quiet.stderr)
            self.assertIn("NOT printed", quiet.stdout)
            loud = run(s, "refresh", "--print-new-token")
            self.assertIn(NEW_TOKEN, loud.stdout)


class Doctor(unittest.TestCase):
    def test_ready(self):
        with serve() as s:
            out = run(s, "doctor")
            self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
            self.assertIn("VERDICT  READY", out.stdout)

    def test_comments_permission_missing_is_a_fix(self):
        with serve(comments_forbidden=True) as s:
            out = run(s, "doctor", "--comments")
            self.assertEqual(out.returncode, 4)
            self.assertIn("VERDICT  FIX", out.stdout)

    def test_expiry_warning_and_failure(self):
        today = dt.datetime.now(dt.timezone.utc).date()
        with serve() as s:
            soon = run(s, "doctor", env_extra={"IG_TOKEN_ISSUED": (today - dt.timedelta(days=50)).isoformat()})
            self.assertIn("WARN  EXPIRY", soon.stdout)
            self.assertIn("VERDICT  PARTIAL", soon.stdout)
            gone = run(s, "doctor", env_extra={"IG_TOKEN_ISSUED": (today - dt.timedelta(days=70)).isoformat()})
            self.assertIn("FAIL  EXPIRY", gone.stdout)
            self.assertNotEqual(gone.returncode, 0)

    def test_dead_token_exits_3(self):
        with serve() as s:
            out = run(s, "doctor", token="IGAAWRONG_TOKEN_0123456789abcdef")
            self.assertEqual(out.returncode, 3)
            self.assertIn("VERDICT  FIX", out.stdout)


if __name__ == "__main__":
    unittest.main()
