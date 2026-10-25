"""Passive, escaped HTML and plain text. No input markup is executed."""

import html
import json
from pathlib import Path

from .core import InputError, http_uri

CSS = """
:root { color-scheme: light dark; font-family: Georgia, 'Times New Roman', serif; }
body { margin: 0; background: #faf8f2; color: #252923; line-height: 1.65; }
main { max-width: 48rem; margin: auto; padding: 3rem 1.5rem 5rem; }
.eyebrow, .meta, nav, .source, .notice, footer { font-family: system-ui, sans-serif; }
.eyebrow { font-size: .75rem; letter-spacing: .12em; text-transform: uppercase; color: #52604b; }
h1 { font-size: clamp(2rem, 6vw, 3.4rem); line-height: 1.1; margin: .7rem 0 1.3rem; }
h2 { font-size: 1.7rem; line-height: 1.25; }
h3 { font-size: 1.1rem; }
a { color: #215b43; text-underline-offset: .2em; overflow-wrap: anywhere; }
a:focus-visible { outline: 3px solid #9b5814; outline-offset: 3px; }
nav { padding: 1.2rem 1.5rem; border: 1px solid #b8c1b1; margin: 2rem 0; }
nav ol { padding-left: 1.5rem; }
section { border-top: 1px solid #b8c1b1; padding-top: 1.4rem; margin-top: 3rem; }
.transcript { white-space: pre-wrap; overflow-wrap: anywhere; font-size: 1.2rem; }
.source, .meta { font-size: .88rem; color: #4d5748; overflow-wrap: anywhere; }
.notice { padding: 1rem; border-left: .3rem solid #9b5814; background: #f4ead7; }
li { margin: .45rem 0; }
footer { font-size: .85rem; margin-top: 3rem; }
@media (prefers-color-scheme: dark) {
 body { background: #20241f; color: #f0f0e8; }
 a { color: #9ee0bb; } .source, .meta, .eyebrow { color: #c0c9ba; }
 .notice { background: #383125; } nav, section { border-color: #677260; }
}
@media print { main { max-width: none; padding: 0; } nav { display: none; }
 section { break-before: page; } a { color: inherit; } }
"""


def esc(value):
    return html.escape(str(value), quote=True)


def link(uri, label):
    try:
        http_uri(uri)
    except InputError:
        return esc(label)
    return f'<a href="{esc(uri)}" rel="noreferrer">{esc(label)}</a>'


def html_document(report):
    title = report["title"]
    parts = [
        '<!doctype html><html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
        "style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'\">",
        f"<title>{esc(title['text'])} — Text companion</title><style>{CSS}</style></head><body>",
        '<main id="top"><header><p class="eyebrow">IIIF text pack / reading companion</p>',
        f'<h1 lang="{esc(title["language"])}" dir="auto">{esc(title["text"])}</h1>',
        f'<p class="meta">{report["summary"]["canvases"]} canvases · '
        f"{report['summary']['texts']} text blocks · Local, self-contained copy</p>",
        f'<p class="source">Manifest: {link(report["manifest"], report["manifest"])}</p></header>',
        '<p class="notice">Text follows the supplied annotation order. It may contain OCR '
        "errors and is not a verified transcription or accessibility certification.</p>",
    ]
    if report["omissions"]:
        parts.append(
            '<p class="notice"><strong>Partial reading pack.</strong> '
            "See the omissions below for missing or unsupported content.</p>"
        )
    parts.append('<nav aria-label="Contents"><h2>Contents</h2><ol>')
    for i, page in enumerate(report["pages"], 1):
        parts.append(
            f'<li><a href="#canvas-{i}" lang="{esc(page["label"]["language"])}" '
            f'dir="auto">{esc(page["label"]["text"])}</a></li>'
        )
    parts.append("</ol></nav>")
    for i, page in enumerate(report["pages"], 1):
        parts.append(
            f'<section id="canvas-{i}" aria-labelledby="heading-{i}">'
            f'<h2 id="heading-{i}" lang="{esc(page["label"]["language"])}" '
            f'dir="auto">{esc(page["label"]["text"])}</h2>'
        )
        parts.append(f'<p class="source">Canvas: {link(page["id"], page["id"])}</p>')
        if not page["texts"]:
            parts.append('<p class="notice">No supported text available for this canvas.</p>')
        for text in page["texts"]:
            parts.append(
                f'<p class="transcript" lang="{esc(text["language"])}" dir="auto">'
                f'{esc(text["text"])}</p><p class="source">'
                f"{link(text['target'], 'Source region')} · "
                f"{link(text['annotation'], 'Annotation')}</p>"
            )
        parts.append('<p class="source"><a href="#top">Back to top</a></p></section>')
    parts.append(
        '<section aria-labelledby="attribution"><h2 id="attribution">Attribution and rights</h2>'
    )
    if not report["attributions"]:
        parts.append(
            "<p>No requiredStatement or rights values were supplied on consumed resources.</p>"
        )
    for item in report["attributions"]:
        parts.append(f'<p class="source">Resource: {esc(item["resource"])}</p>')
        for field in ("label", "value"):
            for entry in item[field]:
                parts.append(
                    f'<p lang="{esc(entry["language"])}" dir="auto">{esc(entry["text"])}</p>'
                )
        if item["rights"]:
            parts.append(f"<p>{link(item['rights'], item['rights'])}</p>")
    parts.append("</section>")
    if report["omissions"]:
        parts.append('<section aria-labelledby="omissions"><h2 id="omissions">Omissions</h2><ul>')
        for item in report["omissions"]:
            parts.append(
                f"<li>{esc(item['code'])}: {esc(item['resource'])} — {esc(item['detail'])}</li>"
            )
        parts.append("</ul></section>")
    parts.append(
        "<footer><p>Generated by iiif-text-pack. Text and attribution remain subject "
        "to their source rights. No remote assets or scripts are loaded."
        "</p></footer></main></body></html>"
    )
    return "\n".join(parts) + "\n"


def plain_text(report):
    lines = [report["title"]["text"], report["manifest"], "", report["ordering"], ""]
    if report["omissions"]:
        lines += ["PARTIAL READING PACK — see omissions below.", ""]
    for page in report["pages"]:
        lines += [page["label"]["text"], page["id"], ""]
        for item in page["texts"]:
            lines += [
                item["text"],
                f"Source: {item['target']}",
                f"Annotation: {item['annotation']}",
                "",
            ]
    lines += ["ATTRIBUTION AND RIGHTS", ""]
    for item in report["attributions"]:
        lines += [item["resource"]]
        lines += [entry["text"] for field in ("label", "value") for entry in item[field]]
        if item["rights"]:
            lines.append(item["rights"])
        lines.append("")
    if report["omissions"]:
        lines += ["OMISSIONS", ""]
        lines += [f"{x['code']}: {x['resource']}: {x['detail']}" for x in report["omissions"]]
    return "\n".join(lines) + "\n"


def write_pack(report, destination, allow_partial=False):
    if report["omissions"] and not allow_partial:
        raise InputError(
            "omissions prevent writing; review them or explicitly allow partial output"
        )
    files = {
        "index.html": html_document(report),
        "text.txt": plain_text(report),
        "report.json": json.dumps(report, ensure_ascii=False, indent=2) + "\n",
    }
    path = Path(destination)
    try:
        path.mkdir()  # Exclusive creation; never reuse or overwrite an existing directory.
        for name, content in files.items():
            with (path / name).open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(content)
    except OSError as exc:
        raise InputError(f"cannot create reading pack: {exc}") from exc
