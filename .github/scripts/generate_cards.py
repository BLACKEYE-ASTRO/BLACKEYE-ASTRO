#!/usr/bin/env python3
"""Generate self-hosted GitHub stats cards (stats, top-langs, streak) as amber-themed SVGs.

Usage:
  GITHUB_TOKEN=... python generate_cards.py --user BLACKEYE-ASTRO --out profile
  python generate_cards.py --out profile --placeholder   # cards with "-" values, no network
  python generate_cards.py --out /tmp/preview --demo     # illustrative numbers, for design checks only

Standard library only, so the workflow needs no pip install.
"""
import argparse
import datetime as dt
import json
import os
import sys
import urllib.request
from pathlib import Path
from xml.sax.saxutils import escape

SANS = "Arial, 'Helvetica Neue', sans-serif"
MONO = "'Fira Code', 'Cascadia Code', Consolas, 'Courier New', monospace"
BG1, BG2 = "#080808", "#19130D"
AMB, DAMB, LAMB, PALE = "#F59E0B", "#D97706", "#FBBF24", "#FDE68A"
WHITE, GREY, DIM = "#FFFFFF", "#D1D1D1", "#888888"
LANG_COLORS = [AMB, LAMB, DAMB, PALE, "#B45309", "#92400E"]


# ------------------------------------------------------------------ data
def gql(token, query, variables):
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={
            "Authorization": f"bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "profile-cards",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        out = json.load(r)
    if "errors" in out:
        raise RuntimeError(json.dumps(out["errors"])[:600])
    return out["data"]


PROFILE_Q = """
query($login: String!) {
  user(login: $login) {
    createdAt
    pullRequests { totalCount }
    issues { totalCount }
    repositoriesContributedTo(contributionTypes: [COMMIT, ISSUE, PULL_REQUEST, REPOSITORY]) { totalCount }
    repositories(first: 100, ownerAffiliations: OWNER, isFork: false) {
      nodes {
        stargazerCount
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) { edges { size node { name } } }
      }
    }
  }
}"""

YEAR_Q = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      totalCommitContributions
      restrictedContributionsCount
      contributionCalendar { weeks { contributionDays { date contributionCount } } }
    }
  }
}"""


def fetch(user, token):
    u = gql(token, PROFILE_Q, {"login": user})["user"]
    repos = u["repositories"]["nodes"]
    stars = sum(r["stargazerCount"] for r in repos)
    langs = {}
    for r in repos:
        for e in r["languages"]["edges"]:
            langs[e["node"]["name"]] = langs.get(e["node"]["name"], 0) + e["size"]

    now = dt.datetime.now(dt.timezone.utc)
    commits, days = 0, {}
    for y in range(int(u["createdAt"][:4]), now.year + 1):
        frm = f"{y}-01-01T00:00:00Z"
        to = f"{y}-12-31T23:59:59Z" if y < now.year else now.strftime("%Y-%m-%dT%H:%M:%SZ")
        c = gql(token, YEAR_Q, {"login": user, "from": frm, "to": to})["user"]["contributionsCollection"]
        commits += c["totalCommitContributions"] + c["restrictedContributionsCount"]
        for w in c["contributionCalendar"]["weeks"]:
            for d in w["contributionDays"]:
                days[dt.date.fromisoformat(d["date"])] = d["contributionCount"]

    today = now.date()
    year_total = sum(v for d, v in days.items() if (today - d).days < 365)
    return {
        "user": user,
        "stars": stars,
        "commits": commits,
        "prs": u["pullRequests"]["totalCount"],
        "issues": u["issues"]["totalCount"],
        "contributed": u["repositoriesContributedTo"]["totalCount"],
        "year": year_total,
        "langs": sorted(langs.items(), key=lambda kv: kv[1], reverse=True),
        "streak": compute_streaks(days, today),
    }


def short(d):
    return f"{d.strftime('%b')} {d.day}" + (f", {d.year}" if d.year != dt.date.today().year else "")


def compute_streaks(days, today):
    longest = (0, None, None)
    run, start = 0, None
    for d in sorted(days):
        if days[d] > 0:
            if run == 0:
                start = d
            run += 1
            if run > longest[0]:
                longest = (run, start, d)
        else:
            run = 0
    d = today if days.get(today, 0) > 0 else today - dt.timedelta(days=1)
    end, cur = d, 0
    while days.get(d, 0) > 0:
        cur += 1
        d -= dt.timedelta(days=1)
    cur_start = end - dt.timedelta(days=cur - 1) if cur else None
    first = min(days) if days else None
    return {
        "total": sum(days.values()),
        "first": first,
        "current": cur,
        "current_range": f"{short(cur_start)} - {short(end)}" if cur else "No active streak",
        "longest": longest[0],
        "longest_range": f"{short(longest[1])} - {short(longest[2])}" if longest[0] else "-",
    }


def placeholder():
    return {
        "user": "BLACKEYE-ASTRO", "stars": None, "commits": None, "prs": None, "issues": None,
        "contributed": None, "year": None, "langs": [],
        "streak": {"total": None, "first": None, "current": None, "current_range": "waiting for first run",
                   "longest": None, "longest_range": "waiting for first run"},
    }


def demo():
    return {
        "user": "BLACKEYE-ASTRO", "stars": 42, "commits": 1284, "prs": 63, "issues": 17,
        "contributed": 9, "year": 812,
        "langs": [("JavaScript", 520), ("TypeScript", 310), ("CSS", 120), ("HTML", 80), ("Python", 40)],
        "streak": {"total": 1560, "first": dt.date(2022, 10, 12), "current": 21,
                   "current_range": "Oct 16 - Nov 5", "longest": 48, "longest_range": "Mar 2 - Apr 18"},
    }


# ---------------------------------------------------------------- render
def fmt(n):
    return "-" if n is None else f"{n:,}"


def brackets(W, H, m=12, s=16):
    d = (f"M{m} {m + s}V{m}H{m + s}M{W - m - s} {m}H{W - m}V{m + s}"
         f"M{W - m} {H - m - s}V{H - m}H{W - m - s}M{m + s} {H - m}H{m}V{H - m - s}")
    return (f'<path d="{d}" stroke="{AMB}" stroke-width="2" stroke-linecap="round" stroke-opacity=".8" fill="none">'
            f'<animate attributeName="stroke-opacity" values=".35;1;.35" dur="3s" repeatCount="indefinite"/></path>')


def frame(W, H, aria, body):
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" fill="none" role="img" aria-label="{escape(aria)}">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop stop-color="{BG1}"/><stop offset="1" stop-color="{BG2}"/></linearGradient>
    <linearGradient id="accent" x1="0" y1="0" x2="1" y2="1"><stop stop-color="{AMB}"/><stop offset="1" stop-color="{DAMB}"/></linearGradient>
    <pattern id="grid" width="32" height="32" patternUnits="userSpaceOnUse">
      <path d="M32 0H0V32" stroke="#FFFFFF" stroke-opacity=".055" fill="none"/>
      <animateTransform attributeName="patternTransform" type="translate" from="0 0" to="32 32" dur="6s" repeatCount="indefinite"/>
    </pattern>
    <clipPath id="card"><rect width="{W}" height="{H}" rx="18"/></clipPath>
  </defs>
  <g clip-path="url(#card)">
    <rect width="{W}" height="{H}" rx="18" fill="url(#bg)"/>
    <rect width="{W}" height="{H}" rx="18" fill="url(#grid)"/>
    {body}
  </g>
  <rect x="1" y="1" width="{W - 2}" height="{H - 2}" rx="17" stroke="{DAMB}" stroke-opacity=".35" fill="none"/>
  {brackets(W, H)}
</svg>
'''


def ring(cx, cy, r, frac, sw=8):
    c = 2 * 3.14159265 * r
    off = c * (1 - max(0.0, min(1.0, frac)))
    return (f'<circle cx="{cx}" cy="{cy}" r="{r}" stroke="#2A2014" stroke-width="{sw}" fill="none"/>'
            f'<circle cx="{cx}" cy="{cy}" r="{r}" stroke="url(#accent)" stroke-width="{sw}" stroke-linecap="round" fill="none" '
            f'stroke-dasharray="{c:.1f}" stroke-dashoffset="{off:.1f}" transform="rotate(-90 {cx} {cy})">'
            f'<animate attributeName="stroke-dashoffset" from="{c:.1f}" to="{off:.1f}" dur="1.4s" fill="freeze"/></circle>')


def stats_svg(d):
    W, H = 500, 230
    rows = [("Total Stars", d["stars"]), ("Commits (all time)", d["commits"]), ("Pull Requests", d["prs"]),
            ("Issues", d["issues"]), ("Contributed to", d["contributed"])]
    body = [
        f'<text x="40" y="52" fill="{AMB}" font-family="{MONO}" font-size="16" font-weight="700">&lt; GITHUB STATS /&gt;</text>',
        f'<text x="{W - 40}" y="52" text-anchor="end" fill="{DIM}" font-family="{MONO}" font-size="12">@{escape(d["user"])}</text>',
    ]
    for i, (label, val) in enumerate(rows):
        y = 90 + i * 28
        body += [
            f'<rect x="40" y="{y - 9}" width="7" height="7" fill="{AMB}" transform="rotate(45 43.5 {y - 5.5})"><animate attributeName="opacity" values=".4;1;.4" dur="3s" begin="-{i * 0.5}s" repeatCount="indefinite"/></rect>',
            f'<text x="60" y="{y}" fill="{GREY}" font-family="{MONO}" font-size="14">{escape(label)}</text>',
            f'<text x="300" y="{y}" text-anchor="end" fill="{WHITE}" font-family="{MONO}" font-size="15" font-weight="700">{fmt(val)}</text>',
        ]
    frac = (d["year"] or 0) / 1000
    body += [
        ring(405, 140, 50, frac),
        f'<text x="405" y="147" text-anchor="middle" fill="{WHITE}" font-family="{MONO}" font-size="24" font-weight="700">{fmt(d["year"])}</text>',
        f'<text x="405" y="167" text-anchor="middle" fill="{DIM}" font-family="{MONO}" font-size="11">past year</text>',
    ]
    return frame(W, H, "GitHub stats", "\n    ".join(body))


def langs_svg(d):
    W, H = 340, 230
    langs = d["langs"][:5]
    total = sum(s for _, s in d["langs"]) or 1
    body = [f'<text x="30" y="52" fill="{AMB}" font-family="{MONO}" font-size="16" font-weight="700">&lt; TOP LANGUAGES /&gt;</text>']
    body.append(f'<clipPath id="bar"><rect x="30" y="68" width="280" height="10" rx="5"/></clipPath>')
    body.append(f'<rect x="30" y="68" width="280" height="10" rx="5" fill="#2A2014"/>')
    x = 30.0
    segs = []
    for i, (name, size) in enumerate(langs):
        w = 280 * size / total
        segs.append(f'<rect x="{x:.1f}" y="68" width="{w:.1f}" height="10" fill="{LANG_COLORS[i]}"><animate attributeName="width" from="0" to="{w:.1f}" dur="0.9s" begin="{i * 0.15:.2f}s" fill="freeze"/></rect>')
        x += w
    body.append(f'<g clip-path="url(#bar)">{"".join(segs)}</g>')
    if not langs:
        body.append(f'<text x="30" y="118" fill="{DIM}" font-family="{MONO}" font-size="13">waiting for first run</text>')
    for i, (name, size) in enumerate(langs):
        y = 108 + i * 23
        body += [
            f'<circle cx="36" cy="{y - 4}" r="4.5" fill="{LANG_COLORS[i]}"/>',
            f'<text x="52" y="{y}" fill="{WHITE}" font-family="{MONO}" font-size="13">{escape(name)}</text>',
            f'<text x="310" y="{y}" text-anchor="end" fill="{GREY}" font-family="{MONO}" font-size="13">{100 * size / total:.1f}%</text>',
        ]
    return frame(W, H, "Top languages", "\n    ".join(body))


def streak_svg(d):
    W, H = 840, 190
    s = d["streak"]
    first = f"{short(s['first'])} - Present" if s["first"] else s["current_range"]
    frac = (s["current"] / s["longest"]) if s["longest"] else 0
    flame = (f'<path d="M0 -13 C 6 -6 10 -2 8 5 C 6 11 -6 11 -8 5 C -10 -1 -4 -4 0 -13 Z" fill="{AMB}" transform="translate(420 22)">'
             f'<animateTransform attributeName="transform" type="translate" values="420 22;420 20;420 22" dur="1.6s" repeatCount="indefinite"/></path>')

    def col(cx, big, label, sub):
        return (f'<text x="{cx}" y="92" text-anchor="middle" fill="{WHITE}" font-family="{MONO}" font-size="34" font-weight="700">{big}</text>'
                f'<text x="{cx}" y="146" text-anchor="middle" fill="{AMB}" font-family="{MONO}" font-size="14">{label}</text>'
                f'<text x="{cx}" y="166" text-anchor="middle" fill="{DIM}" font-family="{MONO}" font-size="12">{escape(sub)}</text>')

    body = [
        f'<line x1="280" y1="40" x2="280" y2="160" stroke="{DAMB}" stroke-opacity=".3"/>',
        f'<line x1="560" y1="40" x2="560" y2="160" stroke="{DAMB}" stroke-opacity=".3"/>',
        col(140, fmt(s["total"]), "Total Contributions", first),
        ring(420, 78, 44, frac),
        f'<text x="420" y="87" text-anchor="middle" fill="{WHITE}" font-family="{MONO}" font-size="28" font-weight="700">{fmt(s["current"])}</text>',
        f'<text x="420" y="146" text-anchor="middle" fill="{AMB}" font-family="{MONO}" font-size="14">Current Streak</text>',
        f'<text x="420" y="166" text-anchor="middle" fill="{DIM}" font-family="{MONO}" font-size="12">{escape(s["current_range"])}</text>',
        flame,
        col(700, fmt(s["longest"]), "Longest Streak", s["longest_range"]),
    ]
    return frame(W, H, "GitHub streak", "\n    ".join(body))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", default=os.environ.get("GITHUB_USER", "BLACKEYE-ASTRO"))
    ap.add_argument("--out", default="profile")
    ap.add_argument("--placeholder", action="store_true")
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()

    if a.placeholder:
        data = placeholder()
    elif a.demo:
        data = demo()
    else:
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            sys.exit("GITHUB_TOKEN is not set")
        data = fetch(a.user, token)

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "stats.svg").write_text(stats_svg(data), encoding="utf-8")
    (out / "top-langs.svg").write_text(langs_svg(data), encoding="utf-8")
    (out / "streak.svg").write_text(streak_svg(data), encoding="utf-8")
    print("wrote stats.svg, top-langs.svg, streak.svg to", out)


if __name__ == "__main__":
    main()