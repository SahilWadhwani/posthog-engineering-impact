"""
analyze.py — Build the Engineering Impact model for PostHog/posthog.

Input:
  data/git_log_raw.txt   complete 90-day squash-merge history (name-only)
  data/review_data.json  identity map (email->login/avatar) + review sample (optional)

Output:
  dashboard/public/data.json   everything the dashboard needs (self-contained)

Philosophy — impact != output:
  We deliberately do NOT rank by lines of code or raw commit counts. We score five
  transparent dimensions and show the raw numbers behind each so a reader can
  validate every ranking.

  1. Scope & Ownership   distinct PRs shipped (squash-merged units of work)
  2. Criticality         work concentrated in hot/shared/core code (not tests/generated)
  3. Collaboration        centrality in the file co-edit network (who works across the
     Centrality           same code as many teammates -> coordination surface / leverage)
  4. Reliability         did their shipped work stick? (penalise reverts of their PRs)
  5. Consistency         sustained contribution across weeks, not a one-week spike

  Heavy-tailed count dims (1,2,3) are normalised to 0-100 by PERCENTILE RANK among
  qualified engineers. Reliability & Consistency use direct, interpretable formulas.
  Impact = weighted average (weights below, sum to 100).
"""
import json
import math
import os
import re
from collections import defaultdict, Counter
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "git_log.txt")
REVIEW = os.path.join(ROOT, "data", "review_data.json")
OUT = os.path.join(ROOT, "dashboard", "public", "data.json")

WINDOW_DAYS = 90
NOW = datetime.now(timezone.utc)
WINDOW_START = NOW - timedelta(days=WINDOW_DAYS)
WEEKS = WINDOW_DAYS / 7.0

WEIGHTS = {
    "scope": 16,
    "criticality": 20,
    "review": 20,
    "centrality": 16,
    "consistency": 15,
    "reliability": 13,
}

DIMENSIONS = [
    {"key": "scope", "label": "Scope & Ownership", "weight": WEIGHTS["scope"],
     "desc": "Distinct PRs shipped in the window. Volume of self-contained, merged units of work — not lines of code."},
    {"key": "criticality", "label": "Criticality", "weight": WEIGHTS["criticality"],
     "desc": "How much of their work lands in hot, shared, core code (backend, migrations, product logic) vs. tests or generated files. Each file weighted by how many other engineers also touch it."},
    {"key": "review", "label": "Review Leverage", "weight": WEIGHTS["review"],
     "desc": "How much they unblock others through code review: the number of distinct teammates whose PRs they left inline review comments on, over the full 90 days. Reviewing broadly is high-leverage, invisible work that raw output metrics miss."},
    {"key": "centrality", "label": "Collaboration Centrality", "weight": WEIGHTS["centrality"],
     "desc": "Eigenvector centrality in the engineer co-edit network: engineers who work across the same files as many teammates sit at the center of coordination and unblock the most people."},
    {"key": "consistency", "label": "Consistency", "weight": WEIGHTS["consistency"],
     "desc": "Share of the 13 weeks in which they shipped at least one PR — sustained contribution rather than a single spike."},
    {"key": "reliability", "label": "Reliability", "weight": WEIGHTS["reliability"],
     "desc": "Did their shipped work stick? Starts at 100 and is penalised when their PRs are later reverted."},
]

BOT_MARKERS = ("[bot]", "dependabot", "renovate", "snyk", "github-actions",
               "posthog-bot", "sentry-io", "greenkeeper", "semantic-release")

NOREPLY_RE = re.compile(r"^(?:\d+\+)?(?P<login>[^@]+)@users\.noreply\.github\.com$", re.I)
PR_RE = re.compile(r"\(#(\d+)\)\s*$")
REVERT_INNER_PR_RE = re.compile(r"\(#(\d+)\)")


def classify(path):
    """Return (area, crit_weight) for a file path."""
    p = path.lower()
    # noise: generated / lockfiles / snapshots
    if ("generated/" in p or p.endswith(".schemas.ts") or "schema_enums" in p
            or "__snapshots__" in p or p.endswith(".snap")
            or p.endswith("-lock.json") or p.endswith(".lock")
            or "yarn.lock" in p or "pnpm-lock.yaml" in p or "package-lock.json" in p):
        crit = 0.1
    elif ("/migrations/" in p):
        crit = 1.6  # schema / DB changes: high impact & risk
    elif ("test_" in os.path.basename(p) or ".test." in p or ".spec." in p
          or "/tests/" in p or "/test/" in p or "/e2e/" in p or "cypress" in p):
        crit = 0.4
    elif p.endswith(".md") or p.startswith("docs/") or "/docs/" in p:
        crit = 0.3
    elif (p.endswith((".yml", ".yaml", ".toml", ".ini", ".cfg", ".txt"))
          or "dockerfile" in p):
        crit = 0.5
    else:
        crit = 1.0

    # area / system
    seg = path.split("/")
    if path.startswith("products/") and len(seg) > 1:
        area = f"products/{seg[1]}"
    elif path.startswith("packages/") and len(seg) > 1:
        area = f"packages/{seg[1]}"
    elif path.startswith("frontend/"):
        area = "frontend"
    elif path.startswith("ee/"):
        area = "ee (enterprise)"
    elif path.startswith("posthog/"):
        area = "posthog (django backend)"
    elif path.startswith("rust/"):
        area = "rust services"
    elif path.startswith("plugin-server/"):
        area = "plugin-server (ingestion)"
    elif path.startswith("dags/") or path.startswith("posthog/dagster"):
        area = "data pipelines"
    elif len(seg) == 1:
        area = "root config"          # bare top-level files (README, configs)
    else:
        area = seg[0] if seg else "other"
    return area, crit


def parse_git_log(path):
    commits = []
    cur = None
    with open(path, "r", errors="replace") as f:
        for line in f:
            line = line.rstrip("\n")
            if line.startswith("C|"):
                if cur:
                    commits.append(cur)
                parts = line.split("|", 5)
                # C | hash | name | email | isoDate | subject
                if len(parts) < 6:
                    cur = None
                    continue
                _, h, name, email, date, subject = parts
                cur = {"hash": h, "name": name, "email": email,
                       "date": date, "subject": subject, "files": []}
            elif line.strip() and cur is not None:
                cur["files"].append(line.strip())
        if cur:
            commits.append(cur)
    return commits


def is_bot(name, email, login):
    hay = f"{name} {email} {login or ''}".lower()
    return any(m in hay for m in BOT_MARKERS) or (login or "").endswith("[bot]")


def load_identity():
    if not os.path.exists(REVIEW):
        return {}, {}, None
    with open(REVIEW) as f:
        rd = json.load(f)
    id_by_email = {k.lower(): v for k, v in rd.get("identity_by_email", {}).items()}
    return id_by_email, rd.get("review_comments", []), rd.get("coverage")


def resolve_identity(email, name, id_by_email):
    """Return (canonical_key, login_or_None, avatar_or_None)."""
    e = (email or "").lower()
    if e in id_by_email:
        info = id_by_email[e]
        login = info.get("login")
        return login, login, info.get("avatar")
    m = NOREPLY_RE.match(e)
    if m:
        login = m.group("login")
        if login.lower() in ("web-flow",):
            return e, None, None
        return login, login, f"https://github.com/{login}.png"
    return e, None, None


def percentile_ranks(values):
    """Map each value to 0-100 percentile rank (ties share the average rank)."""
    n = len(values)
    if n <= 1:
        return [100.0] * n
    order = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        # average count of items strictly-below + half of ties -> smooth percentile
        below = i
        rank = (below + (j - i) / 2.0) / (n - 1) * 100.0
        for k in range(i, j + 1):
            ranks[order[k]] = rank
        i = j + 1
    return ranks


def eigenvector_centrality(nodes, adj, iters=200, tol=1e-9):
    """Weighted eigenvector centrality via power iteration. adj: node->{node:w}."""
    if not nodes:
        return {}
    x = {n: 1.0 / len(nodes) for n in nodes}
    for _ in range(iters):
        nx = {n: 0.0 for n in nodes}
        for n in nodes:
            xn = x[n]
            if xn == 0:
                continue
            for m, w in adj[n].items():
                nx[m] += w * xn
        norm = math.sqrt(sum(v * v for v in nx.values())) or 1.0
        nx = {n: v / norm for n, v in nx.items()}
        if sum(abs(nx[n] - x[n]) for n in nodes) < tol:
            x = nx
            break
        x = nx
    return x


def main():
    print("Parsing git log...")
    commits = parse_git_log(RAW)
    id_by_email, review_comments, review_coverage = load_identity()
    print(f"  {len(commits)} raw commits; {len(id_by_email)} known identities")

    # ---- aggregate per engineer ----
    eng = defaultdict(lambda: {
        "prs": set(), "commits": 0, "files": Counter(), "areas": Counter(),
        "crit_raw": 0.0, "weeks": set(), "first": None, "last": None,
        "name": None, "login": None, "avatar": None,
        "reverts_against": 0, "sample": [],
        "review_authors": set(), "review_prs": set(), "review_comments": 0,
    })
    file_engineers = defaultdict(set)   # file -> set(engineer keys)
    pr_author = {}                       # pr_number -> engineer key
    all_commits_in_window = 0

    parsed = []
    for c in commits:
        try:
            dt = datetime.fromisoformat(c["date"].replace("Z", "+00:00"))
        except Exception:
            continue
        if dt < WINDOW_START:
            continue
        key, login, avatar = resolve_identity(c["email"], c["name"], id_by_email)
        if is_bot(c["name"], c["email"], login):
            continue
        parsed.append((c, dt, key, login, avatar))

    # first pass: PR->author + file->engineers
    for c, dt, key, login, avatar in parsed:
        m = PR_RE.search(c["subject"])
        pr = m.group(1) if m else None
        if pr:
            pr_author[pr] = key
        for fpath in c["files"]:
            file_engineers[fpath].add(key)

    # second pass: aggregate
    for c, dt, key, login, avatar in parsed:
        e = eng[key]
        all_commits_in_window += 1
        e["commits"] += 1
        if e["name"] is None or (login and not e["login"]):
            e["name"] = c["name"]
        if login:
            e["login"] = login
        if avatar and not e["avatar"]:
            e["avatar"] = avatar
        e["weeks"].add(dt.isocalendar()[:2])
        if e["first"] is None or dt < e["first"]:
            e["first"] = dt
        if e["last"] is None or dt > e["last"]:
            e["last"] = dt

        subj = c["subject"]
        m = PR_RE.search(subj)
        pr = m.group(1) if m else None
        if pr:
            e["prs"].add(pr)

        # revert handling: a "Revert ..." commit dings the ORIGINAL PR's author
        if subj.lower().startswith("revert"):
            inner = REVERT_INNER_PR_RE.findall(subj)
            for rp in inner:
                if rp != pr and rp in pr_author:
                    eng[pr_author[rp]]["reverts_against"] += 1

        for fpath in c["files"]:
            area, crit = classify(fpath)
            e["files"][fpath] += 1
            e["areas"][area] += 1
            shared = len(file_engineers[fpath])
            # criticality: weight by intrinsic crit AND how shared/hot the file is
            e["crit_raw"] += crit * math.log(1 + shared)

        # collect sample PRs (prefer feat, then fix), avoid reverts
        if pr and not subj.lower().startswith("revert"):
            e["sample"].append((pr, subj, len(c["files"]), dt))

    # ---- co-edit network (edges weighted by rarity of shared files) ----
    # only meaningful files: touched by 2..60 engineers, and non-trivial crit
    node_keys = [k for k, v in eng.items() if len(v["prs"]) >= 2]
    node_set = set(node_keys)
    adj = {n: defaultdict(float) for n in node_keys}
    for fpath, engs in file_engineers.items():
        engs = [e for e in engs if e in node_set]
        n = len(engs)
        if n < 2 or n > 60:
            continue
        _, crit = classify(fpath)
        if crit < 0.4:
            continue
        w = crit / math.log(2 + n)   # rarer shared files carry more signal
        for i in range(len(engs)):
            for j in range(i + 1, len(engs)):
                a, b = engs[i], engs[j]
                adj[a][b] += w
                adj[b][a] += w
    adj = {n: dict(d) for n, d in adj.items()}
    cent = eigenvector_centrality(node_keys, adj)

    # ---- review leverage: who unblocks whom via inline code review ----
    # review_comments: [{reviewer(login), pr, created_at, body_len}]
    # join reviewer -> engineer key (login == key) and pr -> author via git map
    review_used = 0
    for rc in review_comments:
        rev = rc.get("reviewer")
        pr = rc.get("pr")
        if not rev or not pr:
            continue
        author = pr_author.get(str(pr))
        if not author or author == rev:  # unknown PR (outside window) or self-review
            continue
        e = eng[rev]
        e["review_comments"] += 1
        e["review_authors"].add(author)
        e["review_prs"].add(pr)
        review_used += 1
    review_available = bool(review_comments) and review_coverage \
        and review_coverage.get("review_complete", False)
    print(f"  review comments joined to PR authors: {review_used} "
          f"(complete={review_available})")

    # ---- qualification & scoring ----
    QUALIFY_PRS = 3
    qualified = [k for k, v in eng.items() if len(v["prs"]) >= QUALIFY_PRS]
    print(f"  {len(eng)} humans, {len(qualified)} qualified (>= {QUALIFY_PRS} PRs)")

    scope_raw = [len(eng[k]["prs"]) for k in qualified]
    crit_raw = [eng[k]["crit_raw"] for k in qualified]
    cent_raw = [cent.get(k, 0.0) for k in qualified]
    review_raw = [len(eng[k]["review_authors"]) for k in qualified]

    scope_s = percentile_ranks(scope_raw)
    crit_s = percentile_ranks(crit_raw)
    cent_s = percentile_ranks(cent_raw)
    review_s = percentile_ranks(review_raw)

    engineers = []
    for idx, k in enumerate(qualified):
        v = eng[k]
        prs = len(v["prs"])
        revert_rate = v["reverts_against"] / max(prs, 1)
        reliability = max(0.0, 100.0 * (1 - min(revert_rate * 3.0, 1.0)))
        active_weeks = len(v["weeks"])
        consistency = min(100.0, active_weeks / WEEKS * 100.0)

        scores = {
            "scope": round(scope_s[idx], 1),
            "criticality": round(crit_s[idx], 1),
            "review": round(review_s[idx], 1),
            "centrality": round(cent_s[idx], 1),
            "reliability": round(reliability, 1),
            "consistency": round(consistency, 1),
        }
        impact = sum(scores[d] * WEIGHTS[d] for d in WEIGHTS) / 100.0

        top_areas = [{"area": a, "touches": n} for a, n in v["areas"].most_common(4)]
        # core file-touch share (non-test, non-generated)
        core_touches = sum(n for fp, n in v["files"].items() if classify(fp)[1] >= 1.0)
        total_touches = sum(v["files"].values()) or 1
        core_share = core_touches / total_touches

        samples = sorted(v["sample"], key=lambda s: (0 if s[1].lower().startswith("feat") else 1, -s[2]))
        sample_prs = [{
            "pr": s[0],
            "title": re.sub(r"\s*\(#\d+\)\s*$", "", s[1]),
            "files": s[2],
            "url": f"https://github.com/PostHog/posthog/pull/{s[0]}",
        } for s in samples[:3]]

        login = v["login"]
        engineers.append({
            "key": k,
            "name": v["name"],
            "login": login,
            "profile": f"https://github.com/{login}" if login else None,
            "avatar": v["avatar"] or (f"https://github.com/{login}.png" if login else None),
            "impact": round(impact, 1),
            "scores": scores,
            "highlights": [],  # filled after peer means are known (below)
            "raw": {
                "prs": prs,
                "commits": v["commits"],
                "distinct_files": len(v["files"]),
                "areas": len(v["areas"]),
                "active_weeks": active_weeks,
                "core_share": round(core_share, 2),
                "reverts_against": v["reverts_against"],
                "reviews_given": v["review_comments"],
                "prs_reviewed": len(v["review_prs"]),
                "authors_unblocked": len(v["review_authors"]),
            },
            "top_areas": top_areas,
            "sample_prs": sample_prs,
        })

    engineers.sort(key=lambda e: e["impact"], reverse=True)
    # signature = the dimension where the engineer is MOST above the peer average
    # (so it isn't always "Reliability", which is ~100 for everyone with no reverts)
    dim_means = {d["key"]: (sum(e["scores"][d["key"]] for e in engineers) / max(len(engineers), 1))
                 for d in DIMENSIONS}
    for i, e in enumerate(engineers):
        e["rank"] = i + 1
        best_dim = max(DIMENSIONS, key=lambda d: e["scores"][d["key"]] - dim_means[d["key"]])
        e["signature"] = best_dim["label"]
        # re-order highlights so the engineer's most DISTINCTIVE signals lead
        r = e["raw"]
        top_area = e["top_areas"][0]["area"] if e["top_areas"] else "the codebase"
        cand = [
            ("centrality",
             f"Among the most central engineers in the co-edit network (top {max(1, round(100 - e['scores']['centrality']))}% by collaboration surface) \u2014 works across the same files as many teammates"),
            ("review",
             f"Unblocked {r['authors_unblocked']} different teammates through code review ({r['prs_reviewed']} PRs reviewed)"),
            ("criticality",
             f"{int(r['core_share'] * 100)}% of their work lands in core, non-test code; deepest in {top_area}"),
            ("scope",
             f"Shipped {r['prs']} PRs spanning {r['areas']} areas of the product"),
            ("consistency",
             f"Sustained contribution: active in {r['active_weeks']} of 13 weeks"),
            ("reliability",
             "None of their PRs were reverted in the window" if r["reverts_against"] == 0
             else f"Only {r['reverts_against']} of {r['prs']} PRs were later reverted"),
        ]
        cand.sort(key=lambda c: e["scores"][c[0]] - dim_means[c[0]], reverse=True)
        e["highlights"] = [c[1] for c in cand[:3]]

    # team-level context
    total_prs = len(pr_author)
    area_totals = Counter()
    for k in qualified:
        for a, n in eng[k]["areas"].items():
            area_totals[a] += n

    out = {
        "meta": {
            "repo": "PostHog/posthog",
            "generated_at": NOW.isoformat(),
            "window_start": WINDOW_START.date().isoformat(),
            "window_end": NOW.date().isoformat(),
            "window_days": WINDOW_DAYS,
            "total_commits_analyzed": all_commits_in_window,
            "total_prs": total_prs,
            "total_engineers": len(eng),
            "qualified_engineers": len(qualified),
            "qualify_threshold_prs": QUALIFY_PRS,
            "review_comments_analyzed": sum(len(eng[k]["review_prs"]) for k in eng),
            "review_note": "Review Leverage counts the distinct teammates whose PRs an engineer left inline code-review comments on, over the full 90-day window (fetched via the authenticated GitHub API). It rewards the high-leverage, often-invisible work of unblocking others that raw output metrics miss.",
        },
        "weights": WEIGHTS,
        "dimensions": DIMENSIONS,
        "top_areas": [{"area": a, "touches": n} for a, n in area_totals.most_common(8)],
        "engineers": engineers,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(out, f, indent=None)
    print(f"Wrote {OUT}")
    print("\nTop 10 by Impact:")
    for e in engineers[:10]:
        print(f"  {e['rank']:>2}. {e['impact']:>5}  {e['login'] or e['name']:<22} "
              f"PRs={e['raw']['prs']:>3} areas={e['raw']['areas']:>2} "
              f"weeks={e['raw']['active_weeks']:>2} sig={e['signature']}")


if __name__ == "__main__":
    main()
