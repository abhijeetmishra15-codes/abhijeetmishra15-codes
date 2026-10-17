#!/usr/bin/env python3
"""
Builds the dynamic parts of the profile README:
  - assets/stats.svg      (repos, stars, followers, contributions, streaks)
  - assets/languages.svg  (language share by bytes across your own repos)
  - the "recent activity" block inside README.md

Standard library only. Runs inside GitHub Actions with the built-in GITHUB_TOKEN,
but also works locally:  GITHUB_TOKEN=xxx python scripts/build_profile.py
"""
import html
import json
import os
import re
import sys
import urllib.request
from datetime import date, datetime, timedelta

USER = os.environ.get("PROFILE_USER", "abhijeetmishra15-codes")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BG, BORDER, FG, MUTED, ACCENT = "#0d1117", "#30363d", "#e6edf3", "#7d8590", "#f78166"

LANG_COLORS = {
    "JavaScript": "#f1e05a", "Python": "#3572A5", "Jupyter Notebook": "#DA5B0B",
    "C++": "#f34b7d", "HTML": "#e34c26", "CSS": "#663399", "TypeScript": "#3178c6",
    "Java": "#b07219", "C": "#555555", "Shell": "#89e051",
}


def request(url, data=None):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "profile-readme-builder"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def rest(path):
    return request(f"https://api.github.com{path}")


def graphql(query, variables):
    body = json.dumps({"query": query, "variables": variables}).encode()
    return request("https://api.github.com/graphql", data=body)


# --------------------------------------------------------------------------- data
def fetch_core():
    user = rest(f"/users/{USER}")
    repos = rest(f"/users/{USER}/repos?per_page=100&type=owner&sort=pushed")
    own = [r for r in repos if not r["fork"]]
    stars = sum(r["stargazers_count"] for r in own)

    langs = {}
    for r in own:
        try:
            for name, size in rest(f"/repos/{USER}/{r['name']}/languages").items():
                langs[name] = langs.get(name, 0) + size
        except Exception as e:  # one broken repo shouldn't kill the run
            print(f"language fetch failed for {r['name']}: {e}", file=sys.stderr)
    return user, own, stars, langs


def fetch_contributions():
    """Needs a token. Returns dict or None."""
    if not TOKEN:
        return None
    q = """
    query($login:String!){
      user(login:$login){
        contributionsCollection{
          totalCommitContributions
          totalPullRequestContributions
          contributionCalendar{
            totalContributions
            weeks{contributionDays{date contributionCount}}
          }
        }
      }
    }"""
    try:
        res = graphql(q, {"login": USER})["data"]["user"]["contributionsCollection"]
    except Exception as e:
        print(f"graphql failed: {e}", file=sys.stderr)
        return None

    days = {}
    for w in res["contributionCalendar"]["weeks"]:
        for d in w["contributionDays"]:
            days[d["date"]] = d["contributionCount"]

    # longest streak within the window
    longest = run = 0
    for d in sorted(days):
        run = run + 1 if days[d] > 0 else 0
        longest = max(longest, run)

    # current streak: today may still be empty, so allow starting from yesterday
    cur, cursor = 0, date.today()
    if days.get(cursor.isoformat(), 0) == 0:
        cursor -= timedelta(days=1)
    while days.get(cursor.isoformat(), 0) > 0:
        cur += 1
        cursor -= timedelta(days=1)

    return {
        "year_total": res["contributionCalendar"]["totalContributions"],
        "commits": res["totalCommitContributions"],
        "prs": res["totalPullRequestContributions"],
        "current": cur,
        "longest": longest,
    }


def fetch_recent():
    """Last few commits from public push events."""
    items, seen = [], set()
    try:
        events = rest(f"/users/{USER}/events/public?per_page=60")
    except Exception as e:
        print(f"events failed: {e}", file=sys.stderr)
        return items
    for ev in events:
        if ev["type"] != "PushEvent":
            continue
        repo = ev["repo"]["name"]
        for c in reversed(ev["payload"].get("commits", [])):
            if c["sha"] in seen:
                continue
            seen.add(c["sha"])
            msg = c["message"].splitlines()[0][:70]
            when = datetime.strptime(ev["created_at"], "%Y-%m-%dT%H:%M:%SZ").strftime("%d %b")
            items.append((when, repo, msg, c["sha"][:7]))
            if len(items) >= 5:
                return items
    return items


# --------------------------------------------------------------------------- svg
def esc(s):
    return html.escape(str(s), quote=True)


def stats_svg(user, repos, stars, contrib):
    def cell(x, y, value, label, color=FG):
        return (
            f'<text x="{x}" y="{y}" font-size="30" font-weight="700" fill="{color}">{esc(value)}</text>'
            f'<text x="{x}" y="{y + 22}" font-size="12" fill="{MUTED}" letter-spacing="1">{esc(label.upper())}</text>'
        )

    since = datetime.strptime(user["created_at"], "%Y-%m-%dT%H:%M:%SZ").year
    c = contrib or {}
    dash = "–"
    cells = [
        cell(36, 78, len(repos), "public repos"),
        cell(236, 78, stars, "stars earned"),
        cell(436, 78, user["followers"], "followers"),
        cell(636, 78, c.get("year_total", dash), "contributions / yr", ACCENT),
        cell(36, 170, c.get("current", dash), "day streak", ACCENT),
        cell(236, 170, c.get("longest", dash), "longest streak"),
        cell(436, 170, c.get("commits", dash), "commits / yr"),
        cell(636, 170, c.get("prs", dash), "pull requests / yr"),
    ]
    updated = datetime.utcnow().strftime("%d %b %Y")
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="840" height="240" viewBox="0 0 840 240" font-family="'JetBrains Mono','SF Mono',Menlo,Consolas,monospace">
  <rect x="0.5" y="0.5" width="839" height="239" rx="12" fill="{BG}" stroke="{BORDER}"/>
  <text x="36" y="38" font-size="13" fill="{MUTED}">~/stats <tspan fill="{ACCENT}">@{esc(USER)}</tspan> · on github since {since}</text>
  <line x1="36" y1="50" x2="804" y2="50" stroke="{BORDER}"/>
  {''.join(cells)}
  <text x="804" y="226" font-size="10" fill="{MUTED}" text-anchor="end">auto-updated {updated} UTC</text>
</svg>
"""


def languages_svg(langs):
    total = sum(langs.values()) or 1
    top = sorted(langs.items(), key=lambda kv: kv[1], reverse=True)[:6]
    bar, legend, x = [], [], 36.0
    bar_w = 768.0
    for i, (name, size) in enumerate(top):
        pct = size / total * 100
        w = bar_w * size / total
        color = LANG_COLORS.get(name, "#8b949e")
        bar.append(f'<rect x="{x:.1f}" y="62" width="{max(w, 2):.1f}" height="12" fill="{color}"/>')
        x += w
        col, row = i % 3, i // 3
        lx, ly = 36 + col * 260, 112 + row * 28
        legend.append(
            f'<circle cx="{lx + 5}" cy="{ly - 4}" r="5" fill="{color}"/>'
            f'<text x="{lx + 18}" y="{ly}" font-size="13" fill="{FG}">{esc(name)} '
            f'<tspan fill="{MUTED}">{pct:.1f}%</tspan></text>'
        )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="840" height="190" viewBox="0 0 840 190" font-family="'JetBrains Mono','SF Mono',Menlo,Consolas,monospace">
  <rect x="0.5" y="0.5" width="839" height="189" rx="12" fill="{BG}" stroke="{BORDER}"/>
  <text x="36" y="38" font-size="13" fill="{MUTED}">~/languages <tspan fill="{ACCENT}">by bytes, my own repos</tspan></text>
  <clipPath id="r"><rect x="36" y="62" width="{bar_w:.0f}" height="12" rx="6"/></clipPath>
  <g clip-path="url(#r)">{''.join(bar)}</g>
  {''.join(legend)}
</svg>
"""


# --------------------------------------------------------------------------- readme
def update_readme(recent):
    path = os.path.join(ROOT, "README.md")
    with open(path, encoding="utf-8") as f:
        text = f.read()

    if recent:
        lines = [
            f"- `{when}` &nbsp;[{repo.split('/')[-1]}](https://github.com/{repo}/commit/{sha}) — {esc(msg)}"
            for when, repo, msg, sha in recent
        ]
        block = "\n".join(lines)
    else:
        block = "_Quiet week. Back soon._"

    new = re.sub(
        r"(<!--RECENT:START-->).*?(<!--RECENT:END-->)",
        lambda m: f"{m.group(1)}\n{block}\n{m.group(2)}",
        text,
        flags=re.S,
    )
    if new != text:
        with open(path, "w", encoding="utf-8") as f:
            f.write(new)


def main():
    os.makedirs(os.path.join(ROOT, "assets"), exist_ok=True)
    user, repos, stars, langs = fetch_core()
    contrib = fetch_contributions()
    recent = fetch_recent()

    with open(os.path.join(ROOT, "assets", "stats.svg"), "w", encoding="utf-8") as f:
        f.write(stats_svg(user, repos, stars, contrib))
    with open(os.path.join(ROOT, "assets", "languages.svg"), "w", encoding="utf-8") as f:
        f.write(languages_svg(langs))
    update_readme(recent)
    print("done:", len(repos), "repos,", stars, "stars,", "contrib" if contrib else "no-contrib")


if __name__ == "__main__":
    main()
