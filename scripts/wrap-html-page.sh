#!/usr/bin/env bash
#
# wrap-html-page.sh — wrap an HTML body fragment into a complete,
# self-contained standalone HTML page.
#
# Reads an HTML body fragment on stdin (e.g. the output of GitHub's
# markdown-to-HTML API, or a hand-built landing page body) and writes a
# full HTML document to stdout: a header with site navigation, the
# fragment as page content, and one inline <style> block. Nothing in the
# output references Dokka's generated CSS/JS/assets or any external
# resource — no external stylesheets, fonts, scripts, or images.
#
# Usage:
#   cat fragment.html | wrap-html-page.sh --title "Changelog" \
#     [--active changelog] [--api-href kotlin/index.html] > changelog.html
#
# Options:
#   --title <text>       Required. Used for <title> and the page heading.
#   --active <nav-key>   Optional. One of: overview, api, changelog.
#                         Marks the matching nav item as the current page.
#   --api-href <href>    Optional. Href for the "API reference" nav item.
#                         When omitted, that nav item is not rendered.
#
set -euo pipefail

TITLE=""
ACTIVE=""
API_HREF=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    --title)
      TITLE="$2"
      shift 2
      ;;
    --active)
      ACTIVE="$2"
      shift 2
      ;;
    --api-href)
      API_HREF="$2"
      shift 2
      ;;
    *)
      echo "wrap-html-page.sh: unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

if [ -z "$TITLE" ]; then
  echo "wrap-html-page.sh: --title is required" >&2
  exit 1
fi

BODY_FRAGMENT="$(cat)"

html_escape() {
  local s="$1"
  s="${s//&/&amp;}"
  s="${s//</&lt;}"
  s="${s//>/&gt;}"
  printf '%s' "$s"
}

TITLE_ESCAPED="$(html_escape "$TITLE")"

nav_item() {
  local key="$1" href="$2" label="$3"
  local current=""
  local class=""
  if [ "$key" = "$ACTIVE" ]; then
    current=' aria-current="page"'
    class=' class="active"'
  fi
  printf '<a href="%s"%s%s>%s</a>' "$href" "$class" "$current" "$label"
}

NAV_LINKS="$(nav_item "overview" "index.html" "Overview")"
if [ -n "$API_HREF" ]; then
  NAV_LINKS="$NAV_LINKS
      $(nav_item "api" "$API_HREF" "API reference")"
fi
NAV_LINKS="$NAV_LINKS
      $(nav_item "changelog" "changelog.html" "Changelog")"

cat <<HTML
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${TITLE_ESCAPED}</title>
<style>
  :root {
    color-scheme: light dark;
    --color-bg: #fbfbfa;
    --color-bg-raised: #f2f3f2;
    --color-fg: #1b1e1d;
    --color-fg-muted: #52605a;
    --color-border: #dde1df;
    --color-accent: #2F5D50;
    --color-code-bg: #eef1ef;
    --color-focus-ring: #2F5D50;
  }

  @media (prefers-color-scheme: dark) {
    :root {
      --color-bg: #14171a;
      --color-bg-raised: #1c2023;
      --color-fg: #e7eae8;
      --color-fg-muted: #a7b2ac;
      --color-border: #2c3236;
      --color-accent: #77B9A6;
      --color-code-bg: #20262a;
      --color-focus-ring: #77B9A6;
    }
  }

  * {
    box-sizing: border-box;
  }

  html {
    color-scheme: light dark;
  }

  body {
    margin: 0;
    padding: 0;
    background: var(--color-bg);
    color: var(--color-fg);
    font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
    font-size: 16px;
    line-height: 1.6;
  }

  header {
    border-bottom: 1px solid var(--color-border);
    box-shadow: 0 1px 0 0 var(--color-accent);
  }

  nav {
    max-width: 70ch;
    margin: 0 auto;
    padding: 16px 20px;
    display: flex;
    flex-wrap: wrap;
    gap: 20px;
    align-items: baseline;
  }

  nav a {
    color: var(--color-fg-muted);
    text-decoration: none;
    font-size: 0.95em;
    padding: 2px 0;
    border-bottom: 2px solid transparent;
  }

  nav a:hover {
    color: var(--color-accent);
  }

  nav a.active {
    color: var(--color-accent);
    border-bottom-color: var(--color-accent);
    font-weight: 600;
  }

  main {
    max-width: 70ch;
    margin: 0 auto;
    padding: 24px 20px 64px;
  }

  h1, h2, h3, h4 {
    line-height: 1.3;
    margin-top: 1.6em;
    margin-bottom: 0.6em;
  }

  h1 {
    font-size: 1.8em;
    margin-top: 0;
  }

  h2 {
    font-size: 1.4em;
    border-bottom: 1px solid var(--color-border);
    padding-bottom: 0.3em;
  }

  h3 {
    font-size: 1.15em;
  }

  h4 {
    font-size: 1em;
  }

  p {
    margin: 0.8em 0;
  }

  a {
    color: var(--color-accent);
  }

  a:focus-visible,
  button:focus-visible {
    outline: 2px solid var(--color-focus-ring);
    outline-offset: 2px;
  }

  ul, ol {
    padding-left: 1.4em;
    margin: 0.8em 0;
  }

  li {
    margin: 0.3em 0;
  }

  code {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 0.9em;
    background: var(--color-code-bg);
    padding: 0.15em 0.4em;
    border-radius: 4px;
  }

  pre {
    background: var(--color-code-bg);
    padding: 12px 14px;
    border-radius: 6px;
    overflow-x: auto;
  }

  pre code {
    background: none;
    padding: 0;
  }

  strong {
    font-weight: 600;
  }

  hr {
    border: none;
    border-top: 1px solid var(--color-border);
    margin: 2em 0;
  }

  blockquote {
    margin: 0.8em 0;
    padding: 0.2em 1em;
    border-left: 3px solid var(--color-border);
    color: var(--color-fg-muted);
  }

  table {
    border-collapse: collapse;
    width: 100%;
    margin: 1em 0;
    font-size: 0.95em;
  }

  th, td {
    border: 1px solid var(--color-border);
    padding: 6px 10px;
    text-align: left;
  }

  th {
    background: var(--color-bg-raised);
  }

  footer {
    max-width: 70ch;
    margin: 0 auto;
    padding: 20px;
    color: var(--color-fg-muted);
    font-size: 0.85em;
  }
</style>
</head>
<body>
<header>
  <nav>
      ${NAV_LINKS}
  </nav>
</header>
<main>
<h1>${TITLE_ESCAPED}</h1>
${BODY_FRAGMENT}
</main>
</body>
</html>
HTML
