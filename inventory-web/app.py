#!/usr/bin/env python3
import html
import sqlite3
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

DB_PATH = "/home/camstar915/concierge/concierge.db"
HOST = "0.0.0.0"
PORT = 8080


def db_connect():
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def format_updated(ts):
    if not ts:
        return ""
    try:
        dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        month = dt.strftime("%b")
        day = dt.day
        hour = dt.strftime("%I").lstrip("0") or "12"
        minute = dt.strftime("%M")
        ampm = dt.strftime("%p").lower()
        return f"{month} {day}, {hour}:{minute}{ampm}"
    except Exception:
        return ts


def fetch_inventory():
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT COALESCE(category, 'uncategorized') AS category,
               name,
               COALESCE(quantity, '') AS quantity,
               COALESCE(location, '') AS location,
               COALESCE(notes, '') AS notes,
               COALESCE(updated_at, '') AS updated_at
        FROM bar_inventory
        ORDER BY lower(category), lower(name)
        """
    )
    rows = cur.fetchall()
    conn.close()
    grouped = {}
    for row in rows:
        grouped.setdefault(row["category"], []).append(row)
    return grouped, len(rows)


def fetch_recipes():
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT name, COALESCE(ingredients, '') AS ingredients, COALESCE(instructions, '') AS instructions FROM recipes ORDER BY lower(name)")
    rows = cur.fetchall()
    conn.close()
    return rows


def fetch_call_log(limit=50):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT COALESCE(persona, '') AS persona,
               COALESCE(api, '') AS api,
               COALESCE(digit, '') AS digit,
               COALESCE(event, '') AS event,
               COALESCE(error_code, '') AS error_code,
               COALESCE(error_message, '') AS error_message,
               COALESCE(duration_seconds, '') AS duration_seconds,
               COALESCE(timestamp, '') AS created_at
        FROM call_log
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def layout(title, content, active=""):
    def nav_link(href, label, key):
        cls = "navlink active" if active == key else "navlink"
        return f'<a class="{cls}" href="{href}">{label}</a>'

    return f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{html.escape(title)}</title>
  <style>
    :root {{ color-scheme: dark; }}
    * {{ box-sizing: border-box; }}
    body {{ font-family: system-ui, sans-serif; margin: 0; background: #111827; color: #f9fafb; }}
    .wrap {{ width: min(1200px, 100%); margin: 0 auto; padding: 12px; }}
    h1 {{ margin: 0 0 4px; font-size: 1.5rem; line-height: 1.1; }}
    p.sub {{ margin: 0 0 10px; color: #cbd5e1; font-size: 0.95rem; }}
    .nav {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 0 0 14px; }}
    .navlink {{ text-decoration: none; color: #dbeafe; background: #1e293b; border: 1px solid #334155; padding: 8px 12px; border-radius: 10px; font-size: 0.92rem; }}
    .navlink.active {{ background: #2563eb; color: white; border-color: #2563eb; }}
    .searchbar {{ display: flex; gap: 8px; margin: 0 0 8px; }}
    input {{ flex: 1; padding: 10px 12px; border-radius: 9px; border: 1px solid #334155; background: #0f172a; color: white; font-size: 16px; }}
    button {{ padding: 10px 12px; border-radius: 9px; border: 0; background: #2563eb; color: white; font-size: 15px; }}
    #status {{ margin: 0 0 10px; color: #94a3b8; font-size: 0.9rem; }}
    section {{ margin: 12px 0 16px; }}
    h2 {{ margin: 0 0 6px; font-size: 1rem; border-bottom: 1px solid #334155; padding-bottom: 4px; }}
    .count {{ color: #94a3b8; font-weight: normal; }}
    .list {{ list-style: none; padding: 0; margin: 0; display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 8px; }}
    .item {{ background: #1e293b; border: 1px solid #334155; border-radius: 10px; padding: 8px 10px; }}
    .topline {{ display: flex; align-items: baseline; justify-content: space-between; gap: 10px; margin-bottom: 4px; }}
    .title {{ min-width: 0; }}
    .name {{ font-size: 0.98rem; font-weight: 700; line-height: 1.2; }}
    .qty-inline {{ font-size: 0.84rem; font-weight: 500; color: #cbd5e1; }}
    .updated {{ color: #94a3b8; font-size: 0.78rem; white-space: nowrap; flex-shrink: 0; }}
    .details {{ display: flex; flex-wrap: wrap; gap: 4px 12px; color: #cbd5e1; font-size: 0.84rem; line-height: 1.25; }}
    .hidden {{ display: none !important; }}
    .footer {{ color: #94a3b8; margin-top: 14px; font-size: 0.82rem; }}
    .homegrid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 10px; }}
    .homecard {{ display: block; text-decoration: none; color: inherit; background: #1e293b; border: 1px solid #334155; border-radius: 14px; padding: 14px; }}
    .homecard strong {{ display: block; margin-bottom: 6px; font-size: 1.02rem; }}
    .homecard span {{ color: #cbd5e1; font-size: 0.9rem; line-height: 1.35; }}
    details.recipe {{ background: #1e293b; border: 1px solid #334155; border-radius: 10px; padding: 8px 10px; }}
    details.recipe summary {{ cursor: pointer; font-weight: 700; }}
    .recipe-body {{ margin-top: 8px; color: #cbd5e1; font-size: 0.9rem; line-height: 1.35; }}
    .recipe-block {{ margin-top: 8px; white-space: pre-wrap; }}
    .logtable {{ display: grid; gap: 8px; }}
    .logrow {{ background: #1e293b; border: 1px solid #334155; border-radius: 10px; padding: 8px 10px; }}
    .loghead {{ display: flex; justify-content: space-between; gap: 10px; margin-bottom: 4px; }}
    .logmeta {{ display: flex; flex-wrap: wrap; gap: 6px 12px; color: #cbd5e1; font-size: 0.84rem; }}
    .mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }}
    @media (max-width: 640px) {{
      .wrap {{ padding: 10px; }}
      .list {{ grid-template-columns: 1fr; }}
      .updated {{ font-size: 0.74rem; }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>{html.escape(title)}</h1>
    <p class="sub">Concierge database browser</p>
    <div class="nav">
      {nav_link('/', 'Home', 'home')}
      {nav_link('/inventory', 'Inventory', 'inventory')}
      {nav_link('/recipes', 'Recipes', 'recipes')}
      {nav_link('/calls', 'Call Log', 'calls')}
    </div>
    {content}
    <div class="footer">Serving from {html.escape(DB_PATH)} in read-only mode on port {PORT}.</div>
  </div>
</body>
</html>'''


def home_page():
    content = '''
    <div class="homegrid">
      <a class="homecard" href="/inventory"><strong>Bar Inventory</strong><span>See what’s in stock, where it is, and when it was last updated.</span></a>
      <a class="homecard" href="/recipes"><strong>Recipes</strong><span>Browse saved recipes and search by name, ingredient, or instructions.</span></a>
      <a class="homecard" href="/calls"><strong>Call Log</strong><span>See recent activity from the concierge phone, including persona, event, and errors.</span></a>
    </div>
    '''
    return layout("Concierge Browser", content, active="home")


def inventory_page():
    grouped, total = fetch_inventory()
    sections = []
    for category, items in grouped.items():
        rows_html = []
        for item in items:
            search_blob = " ".join([
                item["category"], item["name"], item["quantity"], item["location"], item["notes"], item["updated_at"]
            ]).lower()
            quantity_inline = f' <span class="qty-inline">({html.escape(item["quantity"])})</span>' if item["quantity"] else ''
            updated_compact = format_updated(item["updated_at"])
            updated_html = f'<span class="updated">{html.escape(updated_compact)}</span>' if updated_compact else ''
            location_html = f'<span><strong>Loc:</strong> {html.escape(item["location"])}</span>' if item["location"] else ''
            notes_html = f'<span><strong>Notes:</strong> {html.escape(item["notes"])}</span>' if item["notes"] else ''
            rows_html.append(
                f'''
                <li class="item inventory-item" data-search="{html.escape(search_blob)}">
                  <div class="topline">
                    <div class="title"><span class="name">{html.escape(item["name"])}{quantity_inline}</span></div>
                    {updated_html}
                  </div>
                  <div class="details">
                    {location_html}
                    {notes_html}
                  </div>
                </li>
                '''
            )
        sections.append(
            f'<section class="category-section"><h2>{html.escape(category.title())} <span class="count">({len(items)})</span></h2><ul class="list">{"".join(rows_html)}</ul></section>'
        )
    content = f'''
    <div class="searchbar">
      <input id="search" type="text" placeholder="Search bar inventory" autocomplete="off" />
      <button id="clearBtn" type="button">Clear</button>
    </div>
    <div id="status">Showing all {total} items.</div>
    {''.join(sections)}
    <script>
      const search = document.getElementById('search');
      const clearBtn = document.getElementById('clearBtn');
      const items = Array.from(document.querySelectorAll('.inventory-item'));
      const sections = Array.from(document.querySelectorAll('.category-section'));
      const status = document.getElementById('status');
      const total = items.length;
      function applyFilter() {{
        const q = search.value.trim().toLowerCase();
        let visible = 0;
        items.forEach(item => {{
          const hay = item.dataset.search || '';
          const match = !q || hay.includes(q);
          item.classList.toggle('hidden', !match);
          if (match) visible++;
        }});
        sections.forEach(section => {{
          const anyVisible = section.querySelectorAll('.inventory-item:not(.hidden)').length > 0;
          section.classList.toggle('hidden', !anyVisible);
        }});
        status.textContent = q ? `Showing ${{visible}} of ${{total}} items for “${{search.value}}”.` : `Showing all ${{total}} items.`;
      }}
      search.addEventListener('input', applyFilter);
      clearBtn.addEventListener('click', () => {{ search.value = ''; applyFilter(); search.focus(); }});
    </script>
    '''
    return layout("Bar Inventory", content, active="inventory")


def recipes_page():
    recipes = fetch_recipes()
    cards = []
    for r in recipes:
        search_blob = " ".join([r["name"], r["ingredients"], r["instructions"]]).lower()
        ingredients = html.escape(r["ingredients"])
        instructions = html.escape(r["instructions"])
        cards.append(
            f'''
            <details class="recipe recipe-item" data-search="{html.escape(search_blob)}">
              <summary>{html.escape(r["name"])}</summary>
              <div class="recipe-body">
                <div class="recipe-block"><strong>Ingredients</strong>\n{ingredients or '—'}</div>
                <div class="recipe-block"><strong>Instructions</strong>\n{instructions or '—'}</div>
              </div>
            </details>
            '''
        )
    content = f'''
    <div class="searchbar">
      <input id="search" type="text" placeholder="Search recipes" autocomplete="off" />
      <button id="clearBtn" type="button">Clear</button>
    </div>
    <div id="status">Showing all {len(recipes)} recipes.</div>
    <div class="logtable">{''.join(cards)}</div>
    <script>
      const search = document.getElementById('search');
      const clearBtn = document.getElementById('clearBtn');
      const items = Array.from(document.querySelectorAll('.recipe-item'));
      const status = document.getElementById('status');
      const total = items.length;
      function applyFilter() {{
        const q = search.value.trim().toLowerCase();
        let visible = 0;
        items.forEach(item => {{
          const hay = item.dataset.search || '';
          const match = !q || hay.includes(q);
          item.classList.toggle('hidden', !match);
          if (match) visible++;
        }});
        status.textContent = q ? `Showing ${{visible}} of ${{total}} recipes for “${{search.value}}”.` : `Showing all ${{total}} recipes.`;
      }}
      search.addEventListener('input', applyFilter);
      clearBtn.addEventListener('click', () => {{ search.value = ''; applyFilter(); search.focus(); }});
    </script>
    '''
    return layout("Recipes", content, active="recipes")


def calls_page():
    rows = fetch_call_log(75)
    cards = []
    for row in rows:
        when = format_updated(row["created_at"])
        title = f'{html.escape(row["event"] or "event")}'
        persona = html.escape(row["persona"]) if row["persona"] else '—'
        api = html.escape(row["api"]) if row["api"] else '—'
        digit = html.escape(str(row["digit"])) if row["digit"] != '' else '—'
        duration = html.escape(str(row["duration_seconds"])) if row["duration_seconds"] != '' else ''
        error_bits = []
        if row["error_code"]:
            error_bits.append(f'<span><strong>Error:</strong> <span class="mono">{html.escape(row["error_code"])}</span></span>')
        if row["error_message"]:
            error_bits.append(f'<span>{html.escape(row["error_message"])}</span>')
        duration_html = f'<span><strong>Duration:</strong> {duration}s</span>' if duration else ''
        cards.append(
            f'''
            <div class="logrow">
              <div class="loghead">
                <strong>{title}</strong>
                <span class="updated">{html.escape(when)}</span>
              </div>
              <div class="logmeta">
                <span><strong>Persona:</strong> {persona}</span>
                <span><strong>API:</strong> {api}</span>
                <span><strong>Digit:</strong> {digit}</span>
                {duration_html}
                {''.join(error_bits)}
              </div>
            </div>
            '''
        )
    content = f'''
    <div id="status">Showing latest {len(rows)} call log entries.</div>
    <div class="logtable">{''.join(cards)}</div>
    '''
    return layout("Call Log", content, active="calls")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        routes = {
            "/": home_page,
            "/inventory": inventory_page,
            "/recipes": recipes_page,
            "/calls": calls_page,
        }
        handler = routes.get(parsed.path)
        if not handler:
            self.send_response(404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Not found")
            return
        body = handler().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return


if __name__ == "__main__":
    server = HTTPServer((HOST, PORT), Handler)
    print(f"Serving inventory on http://{HOST}:{PORT}")
    server.serve_forever()
