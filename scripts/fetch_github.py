"""
Fetch GitHub review + identity data for PostHog/posthog (best-effort).

The local git clone gives complete PR/author/file/date data but identifies
authors only by email. This script adds two things git cannot:
  1. IDENTITY: /commits returns commit-email -> github-login (+ avatar). We fetch
     recent pages to map the active authors we actually rank.
  2. REVIEW LEVERAGE: /pulls/comments (inline code-review comments, bulk) tells us
     which login reviewed which PR -> "who unblocks whom".

Both endpoints are paginated 100/page (1 request/page), newest-first, and stop at
the SINCE cutoff. With a GITHUB_TOKEN we get full coverage (5000 req/hr); otherwise
we spend the 60 req/hr budget wisely and record coverage for transparency.
Fails gracefully: analyze.py works with or without this file.
"""
import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta

OWNER = "PostHog"
REPO = "posthog"
SINCE_DAYS = 92
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "data")

TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
# fall back to a local, gitignored token file so the secret never goes through chat
if not TOKEN:
    _tok_path = os.path.join(OUT_DIR, "gh_token.txt")
    if os.path.exists(_tok_path):
        with open(_tok_path) as _tf:
            _lines = [ln.strip() for ln in _tf if ln.strip() and not ln.strip().startswith("#")]
            TOKEN = _lines[0] if _lines else None
SINCE = datetime.now(timezone.utc) - timedelta(days=SINCE_DAYS)

# Budget split. With a token (5000 req/hr) we can cover the full 90-day window;
# unauthenticated (60 req/hr) we spend the budget wisely and record partial coverage.
COMMIT_PAGES = 40 if TOKEN else 12       # email -> login identity map
REVIEW_PAGES = 1200 if TOKEN else 45     # inline review comments (stops at SINCE cutoff)


def _headers():
    h = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "impact-dashboard-script",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if TOKEN:
        h["Authorization"] = f"Bearer {TOKEN}"
    return h


def _get(url):
    req = urllib.request.Request(url, headers=_headers())
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            remaining = r.headers.get("X-RateLimit-Remaining")
            return json.loads(r.read().decode()), remaining
    except urllib.error.HTTPError as e:
        if e.code == 403:
            print(f"  ! rate limited (403); reset={e.headers.get('X-RateLimit-Reset')}", file=sys.stderr)
        else:
            print(f"  ! HTTP {e.code}: {e.reason}", file=sys.stderr)
        return None, "0"
    except Exception as e:
        print(f"  ! error: {e}", file=sys.stderr)
        return None, "0"


def paginate(endpoint, max_pages, extra=""):
    base = f"https://api.github.com/repos/{OWNER}/{REPO}/{endpoint}"
    items, complete, page = [], True, 1
    while page <= max_pages:
        url = f"{base}?per_page=100&page={page}{extra}"
        data, remaining = _get(url)
        if data is None:
            complete = False
            break
        if not data:
            break
        items.extend(data)
        oldest = data[-1].get("created_at") or (data[-1].get("commit", {}).get("author", {}) or {}).get("date", "")
        print(f"  {endpoint} p{page}: +{len(data)} oldest={oldest} rl={remaining}")
        try:
            if datetime.fromisoformat(oldest.replace("Z", "+00:00")) < SINCE:
                break
        except Exception:
            pass
        if remaining is not None and int(remaining) <= 2:
            print("  ! preserving rate-limit budget; stopping early")
            complete = False
            break
        page += 1
        time.sleep(0.25)
    else:
        complete = False  # hit max_pages, may be truncated
    return items, complete


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"Token: {bool(TOKEN)} | since={SINCE.date()}")

    # 1) identity map: commit email -> {login, avatar}
    print("Fetching commits (identity map)...")
    commits, _ = paginate("commits", COMMIT_PAGES, extra=f"&since={SINCE.isoformat()}")
    identity = {}
    for c in commits:
        author = c.get("author") or {}
        login = author.get("login")
        email = ((c.get("commit") or {}).get("author") or {}).get("email", "")
        if login and email:
            identity.setdefault(email.lower(), {
                "login": login,
                "avatar": author.get("avatar_url"),
            })

    # 2) review leverage: inline code-review comments (reviewer login -> PR)
    print("Fetching inline PR review comments...")
    raw, complete = paginate("pulls/comments", REVIEW_PAGES, extra="&sort=created&direction=desc")
    review_comments = []
    for c in raw:
        pr_url = c.get("pull_request_url", "")
        pr_num = pr_url.rsplit("/", 1)[-1] if pr_url else None
        review_comments.append({
            "reviewer": (c.get("user") or {}).get("login"),
            "pr": pr_num,
            "created_at": c.get("created_at"),
            "body_len": len(c.get("body") or ""),
        })

    out = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "since": SINCE.isoformat(),
        "token_used": bool(TOKEN),
        "identity_by_email": identity,
        "review_comments": review_comments,
        "coverage": {
            "identity_emails": len(identity),
            "review_comments": len(review_comments),
            "review_complete": complete,
        },
    }
    path = os.path.join(OUT_DIR, "review_data.json")
    with open(path, "w") as f:
        json.dump(out, f)
    print(f"Wrote {path}: {len(identity)} identities, {len(review_comments)} review comments (complete={complete})")


if __name__ == "__main__":
    main()
