#!/usr/bin/env python3
"""Render standalone SVGs from a saved GitHub snapshot; no network required."""

import argparse
import base64
from datetime import date, timedelta
from html import escape
import json
from pathlib import Path
import sys
from textwrap import wrap
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
BG = "var(--bg, #0d1117)"
PANEL = "var(--panel, #161b22)"
BORDER = "var(--border, #30363d)"
TILE_BORDER = "var(--tile-border, #252c35)"
TEXT = "var(--text, #e6edf3)"
MUTED = "var(--muted, #9da7b3)"
GREEN = "var(--accent, #7ee787)"
BAR = "var(--bar, #3e9654)"
CELLS = tuple(f"var(--cell-{index}, {color})" for index, color in enumerate(
    ("#21262d", "#0e4429", "#006d32", "#26a641", "#7ee787")))
MONTHS = ("jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez")

THEME_CSS = ''':root {
  --bg: #0d1117; --panel: #161b22; --border: #30363d; --tile-border: #252c35;
  --text: #e6edf3; --muted: #9da7b3; --accent: #7ee787; --bar: #3e9654;
  --cell-0: #21262d; --cell-1: #0e4429; --cell-2: #006d32;
  --cell-3: #26a641; --cell-4: #7ee787;
}
@media (prefers-color-scheme: light) {
  :root {
    --bg: #ffffff; --panel: #f6f8fa; --border: #d1d9e0; --tile-border: #d1d9e0;
    --text: #1f2328; --muted: #59636e; --accent: #1a7f37; --bar: #2da44e;
    --cell-0: #ebedf0; --cell-1: #9be9a8; --cell-2: #40c463;
    --cell-3: #30a14e; --cell-4: #216e39;
  }
}'''

# Keep motion inside the SVGs: GitHub renders these as images without JavaScript.
TERMINAL_CSS = '''@keyframes cursor-blink {
  0%, 49% { opacity: .9; } 50%, 100% { opacity: 0; }
}
@keyframes status-breathe {
  0%, 100% { opacity: 1; } 50% { opacity: .4; }
}
.terminal-cursor { animation: cursor-blink 2s steps(1, end) infinite; }
.status-led { animation: status-breathe 5s ease-in-out infinite; }'''

LOGO_CSS = '''@keyframes green-rise {
  0% { transform: translateY(0); opacity: 0; }
  8% { opacity: 1; }
  82% { transform: translateY(-900px); opacity: 1; }
  83%, 100% { transform: translateY(-900px); opacity: 0; }
}
.logo-scan { opacity: 0; animation: green-rise 7s linear infinite; }'''

STATS_CSS = '''@keyframes chart-replay {
  0%, 100% { transform: scaleY(.12); opacity: .55; }
  24%, 82% { transform: scaleY(1); opacity: 1; }
}
@keyframes metric-breathe {
  0%, 100% { opacity: 1; } 50% { opacity: .8; }
}
.month {
  transform-box: fill-box; transform-origin: center bottom;
  animation: chart-replay 10s cubic-bezier(.4, 0, .2, 1) infinite;
}
.metric-value { animation: metric-breathe 6s ease-in-out infinite; }'''

HEATMAP_CSS = '''@keyframes contribution-wave {
  0%, 50%, 100% { opacity: 1; transform: scale(1); }
  25% { opacity: .45; transform: scale(.8); }
}
.cell[data-active="true"] {
  transform-box: fill-box; transform-origin: center;
  animation: contribution-wave 7s ease-in-out infinite;
}'''

REDUCED_MOTION_CSS = '''@media (prefers-reduced-motion: reduce) {
  .terminal-cursor, .status-led, .logo-scan,
  .cell, .month, .metric-value { animation: none !important; }
}'''


def text(x, y, value, size=18, color=TEXT, extra=""):
    return f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" {extra}>{escape(str(value))}</text>'


def svg(height, title, description, body, css="", width=860, frame=True):
    body = body.replace("><", ">\n<")
    background = (f'<rect x="1" y="1" width="{width - 2}" height="{height - 2}" '
                  f'rx="10" fill="{BG}" stroke="{BORDER}"/>') if frame else ""
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">
<title id="title">{escape(title)}</title>
<desc id="desc">{escape(description)}</desc>
<style>
text {{ font-family: 'SFMono-Regular', Menlo, Consolas, 'Liberation Mono', monospace; }}
{THEME_CSS}
{css}
</style>
{background}
{body}
</svg>
'''


def formatted_date(value):
    return date.fromisoformat(value).strftime("%d/%m/%Y")


def number(value):
    return f"{value:,}".replace(",", ".")


def statistics(days):
    longest = run = 0
    for day in days:
        run = run + 1 if day["count"] else 0
        longest = max(longest, run)
    # An unfinished day with no contributions does not break yesterday's streak.
    recent = days[:-1] if days and not days[-1]["count"] else days
    current = 0
    for day in reversed(recent):
        if not day["count"]:
            break
        current += 1
    return {"total": sum(day["count"] for day in days),
            "active": sum(day["count"] > 0 for day in days),
            "longest": longest, "current": current}


def validate(snapshot, profile):
    if snapshot["username"].lower() != profile["username"].lower():
        raise ValueError("Snapshot belongs to another profile")
    start, end = date.fromisoformat(snapshot["from"]), date.fromisoformat(snapshot["to"])
    if (end - start).days != 364 or snapshot["as_of"] != snapshot["to"]:
        raise ValueError("Snapshot must contain exactly 365 consecutive days")
    if type(snapshot["public_repositories"]) is not int or snapshot["public_repositories"] < 0:
        raise ValueError("Invalid repository count")
    days = snapshot["days"]
    expected = [(start + timedelta(days=i)).isoformat() for i in range(365)]
    if [day["date"] for day in days] != expected:
        raise ValueError("Missing, duplicate, or unsorted contribution dates")
    for day in days:
        if type(day["count"]) is not int or day["count"] < 0:
            raise ValueError("Invalid contribution count")
        if type(day["level"]) is not int or not 0 <= day["level"] <= 4:
            raise ValueError("Invalid contribution level")
        if (day["count"] == 0) != (day["level"] == 0):
            raise ValueError("Contribution color does not match its count")


def monthly_activity(days):
    totals = {}
    for day in days:
        month = day['date'][:7]
        totals[month] = totals.get(month, 0) + day['count']
    return list(totals.items())


def activity_details(days):
    active = sum(day['count'] > 0 for day in days)
    best = max(days, key=lambda day: day['count'], default=None)
    return {'best': best if best and best['count'] else None,
            'average': sum(day['count'] for day in days) / active if active else 0,
            'months': monthly_activity(days)}


def terminal(width, height, command, content):
    body = (f'<rect x="1" y="1" width="{width - 2}" height="{height - 2}" '
            f'rx="10" fill="{BG}" stroke="{BORDER}"/>'
            f'<path d="M1 32H{width - 1}" stroke="{BORDER}"/>')
    for i, color in enumerate(('#ff5f57', '#febc2e', '#28c840')):
        css_class = ' class="status-led"' if i == 2 else ''
        body += f'<circle{css_class} cx="{17 + i * 14}" cy="17" r="3.5" fill="{color}"/>'
    body += text(width / 2 + 18, 21, command, 10, MUTED, 'text-anchor="middle"')
    body += (f'<rect class="terminal-cursor" x="{width - 22}" y="12" '
             f'width="5" height="10" rx="1" fill="{GREEN}"/>')
    return body + content


def monogram_body(profile, width=420, compact=False):
    # Embed the exact supplied artwork, so GitHub's SVG image needs no external fetch.
    artwork = base64.b64encode((ROOT / 'assets/fl-logo.jpeg').read_bytes()).decode('ascii')
    size, top = (232, 58) if compact else (326, 66)
    left = (width - size) / 2
    body = f'''<svg x="{left}" y="{top}" width="{size}" height="{size}" viewBox="210 166 700 700">
<defs>
  <image id="fl-artwork" width="1080" height="1080" href="data:image/jpeg;base64,{artwork}"/>
  <clipPath id="fl-diamond"><path d="M558 172L902 516L559 859L216 516Z"/></clipPath>
  <filter id="fl-white-ink" color-interpolation-filters="sRGB" x="0" y="0" width="100%" height="100%">
    <feColorMatrix type="matrix" values="0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  .2126 .7152 .0722 0 0"/>
    <feComponentTransfer><feFuncA type="linear" slope="10" intercept="-7"/></feComponentTransfer>
  </filter>
  <mask id="fl-letters" maskUnits="userSpaceOnUse" x="210" y="166" width="700" height="700" style="mask-type:alpha">
    <use href="#fl-artwork" filter="url(#fl-white-ink)"/>
  </mask>
  <linearGradient id="fl-green-band" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="{GREEN}" stop-opacity="0"/>
    <stop offset=".45" stop-color="{GREEN}"/>
    <stop offset=".65" stop-color="#22c55e"/>
    <stop offset="1" stop-color="#22c55e" stop-opacity="0"/>
  </linearGradient>
</defs>
<g clip-path="url(#fl-diamond)">
  <use href="#fl-artwork"/>
  <g mask="url(#fl-letters)">
    <rect class="logo-scan" x="210" y="860" width="700" height="170" fill="url(#fl-green-band)"/>
  </g>
</g>
</svg>'''
    name_y = 326 if compact else 430
    body += text(width / 2, name_y, profile['name'], 29, TEXT,
                 'text-anchor="middle" font-weight="700"')
    for index, line in enumerate(wrap(profile['headline'], width=33)):
        body += text(width / 2, name_y + 30 + index * 22, line, 15, MUTED,
                     'text-anchor="middle"')
    body += text(width / 2, 405 if compact else 520, profile['location'], 13, GREEN,
                 'text-anchor="middle"')
    return body


def monogram(profile):
    body = terminal(430, 560, profile['username'] + '@github: ~ / identity',
                    monogram_body(profile, 430))
    return svg(560, 'Monograma FL — ' + profile['name'],
               'Logo FL original em um losango escuro, com uma faixa verde subindo pelas letras. ' +
               profile['headline'] + '. ' + profile['location'] + '.',
               body, TERMINAL_CSS + LOGO_CSS + REDUCED_MOTION_CSS, 430, frame=False)


def heatmap(snapshot, stats, compact=False):
    width = 430 if compact else 860
    days = snapshot['days']
    start = date.fromisoformat(days[0]['date'])
    origin = start - timedelta(days=(start.weekday() + 1) % 7)
    height = 400 if compact else 214
    body = f'<rect width="{width}" height="{height}" rx="10" fill="{BG}"/>'
    body += text(28, 28, f'{number(stats["total"])} contribuições / últimos 365 dias',
                 16 if compact else 18, TEXT)
    body += text(28 if compact else 828, 52 if compact else 28,
                 f'{formatted_date(snapshot["from"])} — {formatted_date(snapshot["to"])}',
                 12, MUTED, '' if compact else 'text-anchor="end"')
    top = 93 if compact else 68
    for band in range(2 if compact else 1):
        for row, label in ((1, 'seg'), (3, 'qua'), (5, 'sex')):
            body += text(29, top + 10 + row * 14 + band * 157, label, 12, MUTED)
    previous_month = None
    label_positions = {}
    for index, day in enumerate(days):
        when = date.fromisoformat(day['date'])
        column, row = divmod((when - origin).days, 7)
        band, column = divmod(column, 27) if compact else (0, column)
        x, y = 76 + column * (12 if compact else 14), top + row * 14 + band * 157
        if when.month != previous_month or compact and column == 0 and row == 0:
            if x - label_positions.get(band, -100) >= 30:
                body += text(x, top - 12 + band * 157, MONTHS[when.month - 1], 12, MUTED)
                label_positions[band] = x
            previous_month = when.month
        caption = f'{formatted_date(day["date"])}: {day["count"]} contribuições'
        active = 'true' if day['count'] else 'false'
        body += (f'<rect class="cell" data-active="{active}" x="{x}" y="{y}" '
                 f'width="{9 if compact else 11}" height="11" rx="2" '
                 f'fill="{CELLS[day["level"]]}" style="animation-delay:-{index * 18}ms">'
                 f'<title>{caption}</title></rect>')
    legend_x, legend_y = (204, 378) if compact else (670, 193)
    body += text(28, legend_y, 'atividade no GitHub', 11, MUTED)
    body += text(legend_x - 44, legend_y, 'menos', 11, MUTED)
    for i, color in enumerate(CELLS):
        body += (f'<rect x="{legend_x + i * 17}" y="{legend_y - 10}" '
                 f'width="11" height="11" rx="2" fill="{color}"/>')
    body += text(legend_x + 92, legend_y, 'mais', 11, MUTED)
    return svg(height, 'Calendário de contribuições',
               f'{stats["total"]} contribuições entre {formatted_date(snapshot["from"])} '
               f'e {formatted_date(snapshot["to"])}. Os tons de verde indicam a intensidade da atividade.',
               body, HEATMAP_CSS + REDUCED_MOTION_CSS, width, frame=False)


def stats_body(snapshot, stats, width=420):
    details = activity_details(snapshot['days'])
    best = details['best']
    metrics = (
        ('sequência atual', stats['current'], 'dias seguidos'),
        ('maior sequência', stats['longest'], 'dias no período'),
        ('contribuições', number(stats['total']), 'últimos 365 dias'),
        ('dias ativos', stats['active'], 'de 365 dias'),
        ('melhor dia', best['count'] if best else 0,
         formatted_date(best['date']) if best else 'sem atividade'),
        ('média / dia ativo', f'{details["average"]:.1f}'.replace('.', ','), 'contribuições'),
    )
    padding, gap = 18, 10
    tile_width = (width - padding * 2 - gap) / 2
    body = ''
    for index, (label, value, context) in enumerate(metrics):
        x = padding + (index % 2) * (tile_width + gap)
        y = 52 + (index // 2) * 96
        body += (f'<rect x="{x}" y="{y}" width="{tile_width}" height="86" '
                 f'rx="6" fill="{PANEL}" stroke="{TILE_BORDER}"/>')
        body += text(x + 12, y + 22, label, 14, MUTED)
        body += text(x + 12, y + 56, value, 32, GREEN if index == 0 else TEXT,
                     f'class="metric-value" font-weight="700" '
                     f'style="animation-delay:-{index * 400}ms"')
        body += text(x + 12, y + 74, context, 12, MUTED)
    chart_y, baseline, chart_height = 344, 478, 86
    body += (f'<rect x="{padding}" y="{chart_y}" width="{width - padding * 2}" '
             f'height="160" rx="6" fill="{PANEL}" stroke="{TILE_BORDER}"/>')
    body += text(30, chart_y + 23, 'contribuições / mês', 12, MUTED)
    months = details['months']
    maximum = max((count for _, count in months), default=0)
    step = (width - 60) / max(1, len(months))
    body += f'<path d="M30 {baseline}H{width - 30}" stroke="{BORDER}"/>'
    for index, (month, count) in enumerate(months):
        x = 30 + index * step
        height = chart_height * count / maximum if maximum else 0
        label = MONTHS[int(month[5:7]) - 1]
        if count:
            body += (f'<rect class="month" x="{x:.2f}" y="{baseline - height:.2f}" '
                     f'width="{step - 8:.2f}" height="{height:.2f}" rx="2" '
                     f'fill="{GREEN if count == maximum else BAR}">'
                     f'<title>{month}: {count} contribuições</title></rect>')
            if count == maximum:
                body += text(round(x + (step - 8) / 2, 2), round(baseline - height - 6, 2),
                             number(count), 10, TEXT, 'text-anchor="middle"')
        body += text(round(x + (step - 8) / 2, 2), baseline + 17, label, 9, MUTED,
                     'text-anchor="middle"')
    body += text(18, 527, f'{snapshot["public_repositories"]} repositórios públicos', 11, MUTED)
    body += text(18, 546, 'atualizado em ' + formatted_date(snapshot['as_of']), 10, MUTED)
    return body


def stats_card(snapshot, stats):
    body = terminal(430, 560, snapshot['username'] + '@github: ~ / stats',
                    stats_body(snapshot, stats, 430))
    return svg(560, 'Estatísticas de ' + snapshot['username'],
               f'{stats["total"]} contribuições; {stats["active"]} dias ativos; '
               f'sequência atual de {stats["current"]} dias; '
               f'maior sequência de {stats["longest"]} dias no período.',
               body, TERMINAL_CSS + STATS_CSS + REDUCED_MOTION_CSS, width=430, frame=False)


def identity(snapshot, profile, stats, compact=False):
    width = 430 if compact else 860
    panel_width = 430 if compact else 420
    portrait_height = 430 if compact else 560
    portrait = terminal(panel_width, portrait_height, profile['username'] + '@github: ~ / identity',
                        monogram_body(profile, panel_width, compact))
    dashboard = terminal(panel_width, 560, profile['username'] + '@github: ~ / stats',
                         stats_body(snapshot, stats, panel_width))
    offset_x, offset_y = (0, 446) if compact else (440, 0)
    body = portrait + f'<g transform="translate({offset_x} {offset_y})">{dashboard}</g>'
    return svg(1006 if compact else 560, profile['name'] + ' — identidade e atividade',
               f'Logo FL em um losango escuro, com faixa verde ascendente. {profile["name"]}, {profile["location"]}. '
               f'{profile["headline"]}. {stats["total"]} contribuições em 365 dias; '
               f'{stats["active"]} dias ativos; maior sequência de {stats["longest"]} dias.',
               body, TERMINAL_CSS + LOGO_CSS + STATS_CSS + REDUCED_MOTION_CSS,
               width, frame=False)


def render(snapshot, profile):
    validate(snapshot, profile)
    stats = statistics(snapshot['days'])
    assets = {'monogram.svg': monogram(profile), 'stats.svg': stats_card(snapshot, stats)}
    for compact, suffix in ((False, ''), (True, '-mobile')):
        assets[f'contributions{suffix}.svg'] = heatmap(snapshot, stats, compact)
        assets[f'identity{suffix}.svg'] = identity(snapshot, profile, stats, compact)
    return assets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "data/github.json")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "assets")
    args = parser.parse_args()
    try:
        snapshot = json.loads(args.data.read_text(encoding="utf-8"))
        profile = json.loads((ROOT / "profile.json").read_text(encoding="utf-8"))
        assets = render(snapshot, profile)
        # Validate all images before replacing any existing one.
        for content in assets.values():
            ElementTree.fromstring(content)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        for filename, content in assets.items():
            target = args.output_dir / filename
            temporary = target.with_suffix(".tmp")
            temporary.write_text(content, encoding="utf-8")
            temporary.replace(target)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"Rendering failed ({type(error).__name__}); check the snapshot and profile.", file=sys.stderr)
        return 1
    print("Rendered " + ", ".join(assets))
    return 0


if __name__ == "__main__":
    sys.exit(main())
