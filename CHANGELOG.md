# Changelog

## 0.1.0

- Export local IIIF v3 supplementing plain-text annotations as passive HTML,
  plain text and JSON with source hashes and annotation/Canvas provenance.
- Resolve explicitly supplied external resources and annotation page pagination.
- Preserve text languages and required attribution on consumed resources.
- Refuse incomplete output by default; opt-in partial output stays visibly marked.
- Reject ambiguous JSON and resource definitions; guard against cyclic references,
  active markup, existing output directories and unsupported text formats.

Validation: automated unit/CLI tests, Ruff, source/wheel builds and isolated wheel
installation. Browser QA covers contents navigation, keyboard activation, Chinese
language metadata, narrow-screen overflow, attribution and passive HTML output.
GitHub CI runs Linux/Python 3.11 and 3.13 and Windows/Python 3.13.

Limitations: no fetching, OCR, IIIF v2, HTML/ALTO/hOCR bodies or inferred reading
order. A complete pack means complete within the documented supported scope.
