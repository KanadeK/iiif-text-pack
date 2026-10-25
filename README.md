# iiif-text-pack

Turn locally saved IIIF Presentation 3 text annotations into a portable reading
companion: one passive HTML file, plain text and a JSON provenance/omission report.

Digitized pages often have transcriptions or OCR in separate annotation pages.
This CLI gathers those saved resources, keeps canvas order and source links, and
preserves attribution. It runs offline with Python 3.11+ and no runtime dependencies.

## Install and make a reading pack

```sh
git clone https://github.com/KanadeK/iiif-text-pack.git
cd iiif-text-pack
python -m venv .venv
# POSIX: source .venv/bin/activate
# PowerShell: .venv\Scripts\Activate.ps1
python -m pip install .
iiif-text-pack examples/manifest.json --resource examples/page-2.json --output reading-pack
```

Expected: **2 canvases, 3 text blocks, 0 omissions**, exit **0**. Open
`reading-pack/index.html` directly in a browser, read `text.txt`, or inspect `report.json`.
The HTML works without a server, JavaScript, fonts or remote assets. Source links
only navigate when you choose to open them. All example text is synthetic and original.

Each `--resource` is an explicitly supplied saved JSON file. Repeat it for external
Canvas, AnnotationPage or Annotation objects, including paginated annotation pages.
The tool matches their `id` values; filenames do not need to match URLs.

```sh
iiif-text-pack manifest.json --resource page1.json --resource page2.json --check
iiif-text-pack manifest.json --resource page1.json --output partial-pack --allow-partial
python -m iiif_text_pack examples/manifest.json --resource examples/page-2.json --check
```

`--check` reports without writing. Missing resources and unsupported text are
explicit omissions. The default **does not create output when omissions exist**.
`--allow-partial` writes a visibly marked partial pack, still with exit code **1**.
The output directory must be new and its parent must exist; existing files are never
overwritten. A filesystem write failure can leave an incomplete new output folder.

Uninstall: `python -m pip uninstall iiif-text-pack`. Delete only generated pack
folders you no longer need; deactivate/remove the dedicated virtual environment
for complete cleanup. Input documents are never modified.

## What is collected

- Canvas `annotations` whose motivation includes `supplementing`.
- Inline `TextualBody` with a nonempty string `value`, `text/plain` format (or no
  format), and optional single language tag. Multiple bodies are retained in order.
- Embedded or explicitly supplied external annotation pages/annotations; `next`
  links are followed only through the supplied local resource index.
- String targets and SpecificResource targets with an unrefined FragmentSelector.
  Targets must name the containing canvas. Fragment geometry/timing is retained as
  provenance, **not validated** or used to infer reading order.
- Required statements and rights on every consumed resource, including bodies.
  All language variants of attribution are kept. HTML inside attribution values is
  shown literally, never executed. Source rights still apply to exported text.

`--language fr-CA` prefers matching labels, then parent tags, then `none`, then the
first language alphabetically. It does not translate/filter the annotation bodies.
Text and labels carry their available language tags in HTML; unknown language is
left unspecified. Language tags receive a syntax check, not IANA registry validation.

## Boundaries

- No downloading, OCR, authentication, image conversion, IIIF v2, JSON-LD expansion
  or external contexts. Resource IDs must be absolute HTTP(S) URIs. No Collection
  traversal, Range/supplementary collections or automatic annotation discovery.
- Painting content (`Canvas.items`) is outside this text-companion scope. Other
  annotation motivations are excluded and counted. This does not extract every text
  that may exist anywhere in a manifest.
- External Text bodies (ALTO, hOCR, plain-text URLs), HTML bodies, Choice and complex
  selectors are reported as unsupported. A canvas with no supported text is flagged.
- Array order is preserved. It may differ from actual reading order; duplicate OCR
  layers in different annotations may repeat text. No deduplication by text value,
  reading-order inference, transcription correction or accessibility certification.
- Duplicate keys, conflicting full resource definitions, malformed structures,
  non-finite JSON numbers and unpaired surrogates are rejected. Cycles/repeated pages
  and annotations produce omissions rather than infinite loops or duplicated output.
- Up to 128 JSON files, 8 MiB each, 64 MiB total; depth 64 and 200,000 nodes per
  document. Inputs/output are held in memory. Standard UTF-8 with optional BOM.

Exit codes: **0** complete within this supported scope, **1** omissions (including
allowed partial output), **2** invalid input or output error. No network is contacted
by the CLI. The generated HTML escapes all text and has a restrictive CSP.

## Why a separate tool?

[IIIF's annotation recipe](https://iiif.io/api/cookbook/recipe/0269-embedded-or-referenced-annotations/)
describes embedded and separate pages; [Presentation 3](https://iiif.io/api/presentation/3.0/)
defines supplementing content. [iiif2annos](https://github.com/glenrobson/iiif2annos)
creates OCR annotations and [IIIF downloaders](https://github.com/YaleDHLab/iiif-downloader)
collect images. This project consumes existing saved text annotations and produces a
small offline reading artifact with an explicit account of what it could not include.

Library:

```python
from iiif_text_pack.core import collect, load_documents
from iiif_text_pack.render import write_pack

documents, sources = load_documents(["manifest.json", "annotations.json"])
report = collect(documents, sources, language="en")
write_pack(report, "new-reading-pack")  # Refuses omissions unless allow_partial=True.
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for tests/build instructions. Code is MIT;
the original example texts and metadata are dedicated to CC0 as their manifest states.
No third-party collection data is redistributed.

## 中文说明

把本地保存的 IIIF v3 文字注释整理为独立 HTML、纯文本和 JSON 证据报告。保留
画布顺序、语言、来源和必要署名。缺失外部注释页或遇到不支持的正文时，默认不
生成文件；显式允许部分输出后会醒目标记，退出码仍为 1。没有下载、OCR 或自动
阅读顺序推断，不将导出成功当作无障碍认证。支持直接在浏览器离线阅读生成文件。
