"""Refresh the profile README stats (incl. private repos) and render langs.svg.

Needs GITHUB_TOKEN: a token of the profile owner with read access to their repos.
Only aggregates are written; private repo names never leave this script.
"""
import datetime as dt
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOP_N = 3
EXCLUDE = set()  # e.g. {"HTML", "CSS"} to hide languages from the card

REPOS_QUERY = """
query($cursor: String) {
  viewer {
    createdAt
    repositories(first: 100, after: $cursor, ownerAffiliations: OWNER, isFork: false) {
      pageInfo { hasNextPage endCursor }
      nodes { languages(first: 20) { edges { size node { name color } } } }
    }
  }
}"""

YEAR_QUERY = """
query($from: DateTime!, $to: DateTime!) {
  viewer {
    contributionsCollection(from: $from, to: $to) {
      totalCommitContributions
      restrictedContributionsCount
      contributionCalendar { weeks { contributionDays { date contributionCount } } }
    }
  }
}"""


def graphql(query, variables):
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        sys.exit("GITHUB_TOKEN is not set")
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={"Authorization": f"bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.load(resp)
    if "errors" in body:
        sys.exit(f"GitHub API error: {body['errors']}")
    return body["data"]["viewer"]


def languages():
    sizes, colors, cursor, created = {}, {}, None, None
    while True:
        viewer = graphql(REPOS_QUERY, {"cursor": cursor})
        created = viewer["createdAt"]
        repos = viewer["repositories"]
        for repo in repos["nodes"]:
            for edge in repo["languages"]["edges"]:
                name = edge["node"]["name"]
                if name in EXCLUDE:
                    continue
                sizes[name] = sizes.get(name, 0) + edge["size"]
                colors[name] = edge["node"]["color"] or "#8b949e"
        if not repos["pageInfo"]["hasNextPage"]:
            break
        cursor = repos["pageInfo"]["endCursor"]
    total = sum(sizes.values()) or 1
    top = sorted(sizes.items(), key=lambda kv: kv[1], reverse=True)[:TOP_N]
    return [(name, 100 * size / total, colors[name]) for name, size in top], created


def contributions(created):
    commits, days = 0, {}
    today = dt.datetime.now(dt.timezone.utc)
    for year in range(int(created[:4]), today.year + 1):
        start = dt.datetime(year, 1, 1, tzinfo=dt.timezone.utc)
        end = min(dt.datetime(year, 12, 31, 23, 59, 59, tzinfo=dt.timezone.utc), today)
        c = graphql(YEAR_QUERY, {"from": start.isoformat(), "to": end.isoformat()})["contributionsCollection"]
        commits += c["totalCommitContributions"] + c["restrictedContributionsCount"]
        for week in c["contributionCalendar"]["weeks"]:
            for day in week["contributionDays"]:
                days[day["date"]] = day["contributionCount"]
    return commits, days


def streaks(days):
    dates = sorted(days)
    longest = run = 0
    for d in dates:
        run = run + 1 if days[d] else 0
        longest = max(longest, run)
    current = 0
    rest = dates[:-1] if dates and not days[dates[-1]] else dates  # today may still be empty
    for d in reversed(rest):
        if not days[d]:
            break
        current += 1
    return current, longest


def days_label(n):
    return f"{n} day" if n == 1 else f"{n} days"


def render_svg(langs):
    row, width = 34, 480
    height = 20 + row * len(langs)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        "<style>text{font:14px -apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;fill:#1f2328}"
        ".pct{fill:#59636e;font-size:13px}.track{fill:#eaeef2}"
        "@media (prefers-color-scheme:dark){text{fill:#e6edf3}.pct{fill:#9198a1}.track{fill:#21262d}}</style>",
    ]
    for i, (name, pct, color) in enumerate(langs):
        y = 16 + i * row
        fill = max(pct / 100 * (width - 20), 6)
        parts += [
            f'<circle cx="16" cy="{y - 5}" r="5" fill="{color}"/>',
            f'<text x="28" y="{y}">{name}</text>',
            f'<text class="pct" x="{width - 10}" y="{y}" text-anchor="end">{pct:.1f}%</text>',
            f'<rect class="track" x="10" y="{y + 7}" width="{width - 20}" height="8" rx="4"/>',
            f'<rect x="10" y="{y + 7}" width="{fill:.1f}" height="8" rx="4" fill="{color}"/>',
        ]
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def main():
    langs, created = languages()
    commits, days = contributions(created)
    current, longest = streaks(days)

    (ROOT / "langs.svg").write_text(render_svg(langs), encoding="utf-8")

    table = (
        "| Total Commits | Current Streak | Longest Streak |\n"
        "|:-:|:-:|:-:|\n"
        f"| {commits} | {days_label(current)} | {days_label(longest)} |"
    )
    readme = ROOT / "README.md"
    text = readme.read_text(encoding="utf-8")
    text = re.sub(
        r"(<!-- stats:start -->).*?(<!-- stats:end -->)",
        lambda m: m.group(1) + "\n" + table + "\n" + m.group(2),
        text,
        flags=re.S,
    )
    readme.write_text(text, encoding="utf-8")
    print(f"commits={commits} current={current} longest={longest} langs={[l[0] for l in langs]}")


if __name__ == "__main__":
    main()
