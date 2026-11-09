"""
build_profile.py — renders the custom SVG cards for the GitHub profile README.

What it does
------------
1. Reads profile.json (your projects + section headers — edit that file, not this one).
2. If a GITHUB_TOKEN is available (it is, inside GitHub Actions), it calls the
   GitHub GraphQL API once to fetch your live stats.
3. Writes SVG files into assets/generated/ which the README embeds.

Runs with the Python standard library only (no pip install needed).

Local run (no token -> placeholder stats):   python scripts/build_profile.py
"""

from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import urllib.request
from xml.sax.saxutils import escape

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "generated"

MONO = "ui-monospace, 'JetBrains Mono', 'Cascadia Code', Consolas, 'SFMono-Regular', Menlo, monospace"
SANS = "'Segoe UI', Inter, 'Helvetica Neue', Arial, sans-serif"

# Design tokens (one palette shared by every card)
BG_0, BG_1 = "#070B14", "#0D1324"
LINE = "#1E293B"
TEXT, MUTED, DIM = "#E2E8F0", "#94A3B8", "#64748B"
CYAN, VIOLET, PINK, GREEN, AMBER = "#22D3EE", "#A78BFA", "#F472B6", "#34D399", "#FBBF24"
METHOD_COLORS = {"GET": CYAN, "POST": GREEN, "PUT": AMBER, "PATCH": VIOLET, "DELETE": PINK}


# --------------------------------------------------------------------------- helpers
def esc(s) -> str:
    return escape(str(s), {'"': "&quot;"})


def wrap(text: str, width: int) -> list[str]:
    """Greedy word-wrap: SVG has no automatic line breaking, so we do it by character count."""
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + (1 if cur else 0) > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}" if cur else w
    if cur:
        lines.append(cur)
    return lines


def fmt(n) -> str:
    if n is None:
        return "—"
    return f"{n/1000:.1f}k" if n >= 10_000 else f"{n:,}"


def svg_open(w: int, h: int, label: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
            f'role="img" aria-label="{esc(label)}"><title>{esc(label)}</title>')


def common_defs(w: int, h: int, uid: str) -> str:
    """Background gradient, glowing gradient border that slowly rotates, and a grid pattern."""
    return f"""
<defs>
  <linearGradient id="bg{uid}" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="{BG_0}"/><stop offset="1" stop-color="{BG_1}"/>
  </linearGradient>
  <linearGradient id="edge{uid}" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="{w}" y2="{h}">
    <stop offset="0" stop-color="{CYAN}"/><stop offset="0.5" stop-color="{VIOLET}" stop-opacity="0.25"/><stop offset="1" stop-color="{PINK}"/>
    <animateTransform attributeName="gradientTransform" type="rotate" values="0 {w/2} {h/2};360 {w/2} {h/2}" dur="14s" repeatCount="indefinite"/>
  </linearGradient>
  <linearGradient id="txt{uid}" x1="0" y1="0" x2="1" y2="0">
    <stop offset="0" stop-color="{CYAN}"/><stop offset="0.55" stop-color="{VIOLET}"/><stop offset="1" stop-color="{PINK}"/>
  </linearGradient>
  <pattern id="grid{uid}" width="28" height="28" patternUnits="userSpaceOnUse">
    <path d="M28 0H0V28" fill="none" stroke="{LINE}" stroke-width="0.8"/>
  </pattern>
  <clipPath id="clip{uid}"><rect x="1" y="1" width="{w-2}" height="{h-2}" rx="18"/></clipPath>
</defs>"""


def frame(w: int, h: int, uid: str, grid_opacity: float = 0.35) -> tuple[str, str]:
    top = (f'<g clip-path="url(#clip{uid})"><rect width="{w}" height="{h}" fill="url(#bg{uid})"/>'
           f'<rect width="{w}" height="{h}" fill="url(#grid{uid})" opacity="{grid_opacity}"/>')
    bottom = (f'</g><rect x="1" y="1" width="{w-2}" height="{h-2}" rx="18" fill="none" '
              f'stroke="url(#edge{uid})" stroke-opacity="0.7" stroke-width="1.5"/></svg>')
    return top, bottom


def pulse_dot(cx: float, cy: float, color: str) -> str:
    return (f'<circle cx="{cx}" cy="{cy}" r="8" fill="{color}" opacity="0.3">'
            f'<animate attributeName="r" values="4;9;4" dur="2s" repeatCount="indefinite"/>'
            f'<animate attributeName="opacity" values="0.45;0;0.45" dur="2s" repeatCount="indefinite"/></circle>'
            f'<circle cx="{cx}" cy="{cy}" r="4" fill="{color}"/>')


def chips(tags: list[str], x: float, y: float, max_x: float, colors=(CYAN, VIOLET, PINK, GREEN, AMBER)) -> str:
    out, cx = [], x
    for i, t in enumerate(tags):
        w = len(t) * 7.6 + 22
        if cx + w > max_x:
            break
        c = colors[i % len(colors)]
        out.append(f'<rect x="{cx:.1f}" y="{y}" width="{w:.1f}" height="26" rx="7" fill="{c}" fill-opacity="0.08" '
                   f'stroke="{c}" stroke-opacity="0.35"/>'
                   f'<text x="{cx + w/2:.1f}" y="{y+17.5}" text-anchor="middle" font-family="{MONO}" font-size="12.5" fill="{c}">{esc(t)}</text>')
        cx += w + 8
    return "".join(out)


# --------------------------------------------------------------------------- section headers
def section_header(method: str, route: str, note: str, latency: str, uid: str) -> str:
    w, h = 1200, 64
    c = METHOD_COLORS.get(method, CYAN)
    mw = len(method) * 11 + 28
    return f"""{svg_open(w, h, f'{method} {route} — {note}')}
<defs>
  <linearGradient id="ln{uid}" x1="0" y1="0" x2="1" y2="0">
    <stop offset="0" stop-color="{c}" stop-opacity="0.9"/><stop offset="0.6" stop-color="{VIOLET}" stop-opacity="0.35"/><stop offset="1" stop-color="{PINK}" stop-opacity="0"/>
  </linearGradient>
  <linearGradient id="sw{uid}" x1="0" y1="0" x2="1" y2="0">
    <stop offset="0" stop-color="#fff" stop-opacity="0"/><stop offset="0.5" stop-color="#fff" stop-opacity="0.9"/><stop offset="1" stop-color="#fff" stop-opacity="0"/>
  </linearGradient>
</defs>
<rect x="2" y="10" width="{mw}" height="32" rx="8" fill="{c}" fill-opacity="0.12" stroke="{c}" stroke-opacity="0.6"/>
<text x="{2 + mw/2}" y="31.5" text-anchor="middle" font-family="{MONO}" font-size="15" font-weight="700" fill="{c}">{esc(method)}</text>
<text x="{mw + 18}" y="33" font-family="{MONO}" font-size="22" font-weight="600" fill="{TEXT}">{esc(route)}</text>
<text x="{mw + 36 + len(route) * 13.3:.0f}" y="32" font-family="{MONO}" font-size="14" fill="{DIM}"># {esc(note)}</text>
<text x="1196" y="32" text-anchor="end" font-family="{MONO}" font-size="14" fill="{DIM}"><tspan fill="{GREEN}">200 OK</tspan> · {esc(latency)}</text>
<rect x="2" y="55" width="1196" height="2" rx="1" fill="url(#ln{uid})"/>
<rect x="-160" y="55" width="160" height="2" fill="url(#sw{uid})" opacity="0.8">
  <animate attributeName="x" values="-160;1200" dur="3.2s" repeatCount="indefinite"/>
</rect>
</svg>"""


# --------------------------------------------------------------------------- project cards
def project_card(p: dict, uid: str) -> str:
    w, h = 600, 290
    method = p.get("method", "GET").upper()
    c = METHOD_COLORS.get(method, CYAN)
    mw = len(method) * 9 + 22
    top, bottom = frame(w, h, uid)
    desc_lines = wrap(p["description"], 60)[:3]
    desc = "".join(f'<text x="28" y="{150 + i*23}" font-family="{SANS}" font-size="15.5" fill="{MUTED}">{esc(l)}</text>'
                   for i, l in enumerate(desc_lines))
    badge = p.get("badge", "")
    badge_svg = ""
    if badge:
        bw = len(badge) * 8 + 20
        badge_svg = (f'<rect x="{w - 28 - bw}" y="96" width="{bw}" height="24" rx="12" fill="{AMBER}" fill-opacity="0.1" '
                     f'stroke="{AMBER}" stroke-opacity="0.5"/><text x="{w - 28 - bw/2}" y="112.5" text-anchor="middle" '
                     f'font-family="{MONO}" font-size="11.5" font-weight="700" fill="{AMBER}" letter-spacing="1">{esc(badge)}</text>')
    role = p.get("role", "author")
    role_svg = "" if role == "author" else f'  ·  role: <tspan fill="{MUTED}">{esc(role)}</tspan>'
    return f"""{svg_open(w, h, f"{p['title']} — {p['description']}")}{common_defs(w, h, uid)}
{top}
<circle cx="{w-40}" cy="40" r="120" fill="{c}" opacity="0.06"/>
<rect x="28" y="26" width="{mw}" height="26" rx="6" fill="{c}" fill-opacity="0.14" stroke="{c}" stroke-opacity="0.6"/>
<text x="{28 + mw/2}" y="43.5" text-anchor="middle" font-family="{MONO}" font-size="13" font-weight="700" fill="{c}">{esc(method)}</text>
<text x="{38 + mw}" y="44" font-family="{MONO}" font-size="15" fill="{TEXT}">{esc(p.get('route', '/'))}</text>
{pulse_dot(w - 118, 39, GREEN)}
<text x="{w - 28}" y="44" text-anchor="end" font-family="{MONO}" font-size="13" fill="{GREEN}">200 OK</text>
<path d="M28 70 H{w-28}" stroke="{LINE}"/>
<text x="28" y="116" font-family="{SANS}" font-size="27" font-weight="700" fill="url(#txt{uid})">{esc(p['title'])}</text>
{badge_svg}
{desc}
{chips(p.get('tags', []), 28, 222, w - 28)}
<text x="28" y="272" font-family="{MONO}" font-size="12.5" fill="{DIM}">repo: <tspan fill="{MUTED}">{esc(p['repo'])}</tspan>{role_svg}</text>
<text x="{w-28}" y="272" text-anchor="end" font-family="{MONO}" font-size="12.5" fill="{CYAN}">open repo ↗</text>
{bottom}"""


def contribution_card(p: dict, uid: str) -> str:
    w, h = 1200, 170
    top, bottom = frame(w, h, uid)
    desc_lines = wrap(p["description"], 92)[:2]
    desc = "".join(f'<text x="250" y="{92 + i*23}" font-family="{SANS}" font-size="15.5" fill="{MUTED}">{esc(l)}</text>'
                   for i, l in enumerate(desc_lines))
    return f"""{svg_open(w, h, f"Contributed to {p['title']} — {p['description']}")}{common_defs(w, h, uid)}
{top}
<circle cx="110" cy="85" r="150" fill="{VIOLET}" opacity="0.07"/>
<g font-family="{MONO}">
  <text x="34" y="52" font-size="13" fill="{DIM}">git log --author</text>
  <text x="34" y="84" font-size="13" fill="{VIOLET}">● merged into</text>
  <text x="34" y="108" font-size="13" fill="{MUTED}">{esc(p['repo'].split('/')[0])}/</text>
</g>
<path d="M226 30 V140" stroke="{LINE}"/>
<text x="250" y="60" font-family="{SANS}" font-size="26" font-weight="700" fill="url(#txt{uid})">{esc(p['title'])}</text>
<text x="{262 + len(p['title']) * 15}" y="59" font-family="{MONO}" font-size="12.5" fill="{AMBER}">{esc(p.get('badge', ''))}</text>
{desc}
{chips(p.get('tags', []), 250, 128, 1000)}
<text x="1170" y="60" text-anchor="end" font-family="{MONO}" font-size="12.5" fill="{DIM}">role: <tspan fill="{MUTED}">{esc(p.get('role', 'contributor'))}</tspan></text>
<text x="1170" y="146" text-anchor="end" font-family="{MONO}" font-size="12.5" fill="{CYAN}">open repo ↗</text>
{bottom}"""


# --------------------------------------------------------------------------- live stats
QUERY = """
query($login: String!) {
  user(login: $login) {
    createdAt
    followers { totalCount }
    pullRequests { totalCount }
    repositoriesContributedTo(contributionTypes: [COMMIT, PULL_REQUEST, ISSUE, REPOSITORY]) { totalCount }
    repositories(ownerAffiliations: OWNER, isFork: false, privacy: PUBLIC, first: 100) {
      totalCount
      nodes {
        stargazerCount
        languages(first: 8, orderBy: {field: SIZE, direction: DESC}) { edges { size node { name color } } }
      }
    }
    contributionsCollection {
      totalCommitContributions
      contributionCalendar { totalContributions weeks { contributionDays { date contributionCount } } }
    }
  }
}"""


def fetch_stats(login: str, token: str) -> dict:
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": QUERY, "variables": {"login": login}}).encode(),
        headers={"Authorization": f"bearer {token}", "Content-Type": "application/json",
                 "User-Agent": "profile-readme-builder"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        payload = json.load(r)
    if "errors" in payload:
        raise RuntimeError(payload["errors"])
    u = payload["data"]["user"]
    cal = u["contributionsCollection"]["contributionCalendar"]
    days = [d for wk in cal["weeks"] for d in wk["contributionDays"]]
    weekly = [sum(d["contributionCount"] for d in wk["contributionDays"]) for wk in cal["weeks"]]

    # streaks: walk the calendar day by day
    longest = run = 0
    for d in days:
        run = run + 1 if d["contributionCount"] > 0 else 0
        longest = max(longest, run)
    current = 0
    rev = list(reversed(days))
    if rev and rev[0]["contributionCount"] == 0:  # today not counted yet -> start from yesterday
        rev = rev[1:]
    for d in rev:
        if d["contributionCount"] == 0:
            break
        current += 1

    langs: dict[str, dict] = {}
    for repo in u["repositories"]["nodes"]:
        for e in repo["languages"]["edges"]:
            n = e["node"]["name"]
            langs.setdefault(n, {"size": 0, "color": e["node"]["color"] or MUTED})
            langs[n]["size"] += e["size"]

    return {
        "contributions": cal["totalContributions"],
        "commits": u["contributionsCollection"]["totalCommitContributions"],
        "prs": u["pullRequests"]["totalCount"],
        "repos": u["repositories"]["totalCount"],
        "stars": sum(r["stargazerCount"] for r in u["repositories"]["nodes"]),
        "contributed_to": u["repositoriesContributedTo"]["totalCount"],
        "current_streak": current,
        "longest_streak": longest,
        "weekly": weekly[-52:],
        "languages": langs,
        "synced": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }


def placeholder_stats() -> dict:
    return {k: None for k in ("contributions", "commits", "prs", "repos", "stars", "contributed_to",
                              "current_streak", "longest_streak")} | {
        "weekly": [], "languages": {}, "synced": "pending — run the workflow once"}


def metrics_card(s: dict, exclude: list[str], uid: str = "m") -> str:
    w, h = 1200, 430
    top, bottom = frame(w, h, uid, grid_opacity=0.25)
    tiles = [
        ("contributions · 12mo", fmt(s["contributions"]), CYAN),
        ("commits · 12mo", fmt(s["commits"]), VIOLET),
        ("uptime streak", f"{fmt(s['current_streak'])}d" if s["current_streak"] is not None else "—", GREEN),
        ("longest streak", f"{fmt(s['longest_streak'])}d" if s["longest_streak"] is not None else "—", AMBER),
        ("pull requests", fmt(s["prs"]), PINK),
        ("repos contributed", fmt(s["contributed_to"]), CYAN),
    ]
    tile_svg = []
    for i, (label, value, c) in enumerate(tiles):
        col, row = i % 2, i // 2
        x, y = 28 + col * 222, 86 + row * 102
        tile_svg.append(
            f'<g><animate attributeName="opacity" values="0;0;1" keyTimes="0;{0.15 * i / (0.15 * i + 0.5):.3f};1" dur="{0.15 * i + 0.5:.2f}s" fill="freeze"/>'
            f'<rect x="{x}" y="{y}" width="210" height="90" rx="12" fill="#0B1120" stroke="{c}" stroke-opacity="0.28"/>'
            f'<rect x="{x}" y="{y + 18}" width="3" height="54" rx="1.5" fill="{c}"/>'
            f'<text x="{x + 18}" y="{y + 30}" font-family="{MONO}" font-size="11.5" fill="{DIM}" letter-spacing="0.6">{esc(label.upper())}</text>'
            f'<text x="{x + 18}" y="{y + 70}" font-family="{SANS}" font-size="34" font-weight="700" fill="{TEXT}">{esc(value)}</text></g>')

    # throughput chart — contributions per week, drawn like a request-rate graph
    cx0, cy0, cw, ch = 500, 96, 668, 196
    weekly = s["weekly"]
    chart = [f'<rect x="{cx0}" y="{cy0 - 10}" width="{cw}" height="{ch + 34}" rx="12" fill="#0B1120" stroke="{LINE}"/>']
    for gy in range(1, 4):
        yy = cy0 + 10 + gy * (ch - 20) / 4
        chart.append(f'<path d="M{cx0 + 14} {yy:.1f} H{cx0 + cw - 14}" stroke="{LINE}" stroke-dasharray="2 6"/>')
    if weekly and max(weekly) > 0:
        peak = max(weekly)
        n = len(weekly)
        pts = [(cx0 + 18 + i * (cw - 36) / (n - 1), cy0 + ch - 6 - (v / peak) * (ch - 34)) for i, v in enumerate(weekly)]
        line = "M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in pts)
        area = line + f" L{pts[-1][0]:.1f} {cy0 + ch - 6} L{pts[0][0]:.1f} {cy0 + ch - 6} Z"
        px, py = max(pts, key=lambda p: -p[1])
        chart.append(f"""
<defs><linearGradient id="area{uid}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{CYAN}" stop-opacity="0.35"/><stop offset="1" stop-color="{VIOLET}" stop-opacity="0"/></linearGradient></defs>
<path d="{area}" fill="url(#area{uid})"><animate attributeName="opacity" values="0;0;1" keyTimes="0;0.6;1" dur="2s" fill="freeze"/></path>
<path d="{line}" fill="none" stroke="url(#txt{uid})" stroke-width="2.4" stroke-linejoin="round" stroke-linecap="round" pathLength="1" stroke-dasharray="1" stroke-dashoffset="0">
  <animate attributeName="stroke-dashoffset" values="1;1;0" keyTimes="0;0.14;1" dur="2.1s" fill="freeze"/></path>
{pulse_dot(px, py, PINK)}
<text x="{min(px + 10, cx0 + cw - 90):.1f}" y="{max(py - 10, cy0 + 12):.1f}" font-family="{MONO}" font-size="11.5" fill="{PINK}">peak {peak}/wk</text>""")
    else:
        chart.append(f'<text x="{cx0 + cw/2}" y="{cy0 + ch/2}" text-anchor="middle" font-family="{MONO}" font-size="14" fill="{DIM}">'
                     f'awaiting first sync · Actions → “Build profile” → Run workflow</text>')
    chart.append(f'<text x="{cx0 + 18}" y="{cy0 + ch + 16}" font-family="{MONO}" font-size="11.5" fill="{DIM}">contributions / week · last 52 weeks</text>')
    chart.append(f'<text x="{cx0 + cw - 18}" y="{cy0 + ch + 16}" text-anchor="end" font-family="{MONO}" font-size="11.5" fill="{DIM}">now →</text>')

    # language traffic split
    langs = {k: v for k, v in s["languages"].items() if k not in exclude}
    total = sum(v["size"] for v in langs.values())
    bar_y, bar_x, bar_w = 352, 500, 668
    lang_svg = [f'<text x="{bar_x}" y="{bar_y - 10}" font-family="{MONO}" font-size="11.5" fill="{DIM}" letter-spacing="0.6">TRAFFIC SPLIT · LANGUAGES</text>']
    if total:
        top5 = sorted(langs.items(), key=lambda kv: -kv[1]["size"])[:5]
        other = total - sum(v["size"] for _, v in top5)
        segs = [(k, v["size"], v["color"]) for k, v in top5] + ([("Other", other, "#475569")] if other > 0 else [])
        x = bar_x
        lang_svg.append(f'<clipPath id="bar{uid}"><rect x="{bar_x}" y="{bar_y}" width="{bar_w}" height="12" rx="6"/></clipPath><g clip-path="url(#bar{uid})">')
        for name, size, color in segs:
            sw = bar_w * size / total
            lang_svg.append(f'<rect x="{x:.1f}" y="{bar_y}" width="{sw:.1f}" height="12" fill="{color}"/>')
            x += sw
        lang_svg.append("</g>")
        lx = bar_x
        for name, size, color in segs:
            label = f"{name} {100 * size / total:.0f}%"
            lang_svg.append(f'<circle cx="{lx + 5}" cy="{bar_y + 34}" r="5" fill="{color}"/>'
                            f'<text x="{lx + 15}" y="{bar_y + 38.5}" font-family="{MONO}" font-size="12" fill="{MUTED}">{esc(label)}</text>')
            lx += len(label) * 7.4 + 34
    else:
        lang_svg.append(f'<rect x="{bar_x}" y="{bar_y}" width="{bar_w}" height="12" rx="6" fill="{LINE}"/>')

    return f"""{svg_open(w, h, 'Live GitHub metrics for Nishanth2468')}{common_defs(w, h, uid)}
{top}
<circle cx="1100" cy="40" r="220" fill="{VIOLET}" opacity="0.05"/>
<circle cx="80" cy="400" r="220" fill="{CYAN}" opacity="0.05"/>
<circle cx="34" cy="38" r="6" fill="#F87171"/><circle cx="54" cy="38" r="6" fill="{AMBER}"/><circle cx="74" cy="38" r="6" fill="{GREEN}"/>
<text x="98" y="43" font-family="{MONO}" font-size="14" fill="{MUTED}">GET <tspan fill="{TEXT}">/metrics</tspan>  <tspan fill="{DIM}"># live from the GitHub API</tspan></text>
{pulse_dot(1172 - len('synced ' + s['synced']) * 7.6 - 16, 38, GREEN)}
<text x="1172" y="43" text-anchor="end" font-family="{MONO}" font-size="12.5" fill="{DIM}">synced {esc(s['synced'])}</text>
<path d="M28 62 H1172" stroke="{LINE}"/>
{''.join(tile_svg)}
{''.join(chart)}
{''.join(lang_svg)}
{bottom}"""


# --------------------------------------------------------------------------- main
def main() -> None:
    cfg = json.loads((ROOT / "profile.json").read_text(encoding="utf-8"))
    OUT.mkdir(parents=True, exist_ok=True)

    for i, sec in enumerate(cfg["sections"]):
        (OUT / f"section-{sec['id']}.svg").write_text(
            section_header(sec["method"], sec["route"], sec["note"], sec.get("latency", "12ms"), f"s{i}"), encoding="utf-8")

    for i, p in enumerate(cfg["projects"]):
        (OUT / f"project-{p['id']}.svg").write_text(project_card(p, f"p{i}"), encoding="utf-8")

    for i, p in enumerate(cfg.get("contributions", [])):
        (OUT / f"contrib-{p['id']}.svg").write_text(contribution_card(p, f"c{i}"), encoding="utf-8")

    token = os.environ.get("GITHUB_TOKEN")
    stats = placeholder_stats()
    if token:
        try:
            stats = fetch_stats(cfg["username"], token)
        except Exception as exc:  # keep the old card rather than breaking the profile
            print(f"stats fetch failed: {exc}")
            if (OUT / "metrics.svg").exists():
                return
    (OUT / "metrics.svg").write_text(metrics_card(stats, cfg.get("exclude_languages", [])), encoding="utf-8")
    print(f"built {len(list(OUT.glob('*.svg')))} SVGs into {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
