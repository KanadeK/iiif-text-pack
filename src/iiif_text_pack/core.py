"""Collect a bounded, explicitly supported subset of local IIIF v3 text."""

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

MAX_BYTES = 8 * 1024 * 1024
MAX_TOTAL = 64 * 1024 * 1024
MAX_DOCUMENTS = 128
MAX_NODES = 200_000
LANG = re.compile(r"[A-Za-z]{1,8}(?:-[A-Za-z0-9]{1,8})*\Z", re.ASCII)
FULL = {
    "Manifest": "items",
    "Canvas": "annotations",
    "AnnotationPage": "items",
    "Annotation": "body",
}


class InputError(ValueError):
    """Cannot interpret a local document safely and without ambiguity."""


def http_uri(value):
    if not isinstance(value, str) or re.search(r"[\s\x00-\x1f\x7f\\]", value):
        raise InputError("resource ID must be an absolute HTTP(S) URI without controls")
    try:
        parts = urlsplit(value)
        valid = (
            parts.scheme in {"http", "https"}
            and parts.hostname
            and parts.username is None
            and parts.password is None
        )
        _ = parts.port
    except ValueError as exc:
        raise InputError("invalid resource URI") from exc
    if not valid:
        raise InputError("only absolute HTTP(S) resource identifiers are supported")
    return value


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InputError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _constant(value):
    raise InputError(f"non-finite JSON number: {value}")


def walk(document):
    stack = [(document, 0)]
    count = 0
    while stack:
        item, depth = stack.pop()
        count += 1
        if count > MAX_NODES or depth > 64:
            raise InputError("JSON exceeds 200000 nodes or depth 64")
        if isinstance(item, dict):
            yield item
            stack.extend((v, depth + 1) for v in reversed(list(item.values())))
            stack.extend((k, depth + 1) for k in item)
        elif isinstance(item, list):
            stack.extend((v, depth + 1) for v in reversed(item))
        elif isinstance(item, str):
            try:
                item.encode("utf-8")
            except UnicodeError as exc:
                raise InputError("unpaired Unicode surrogate in JSON") from exc
            if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", item):
                raise InputError("unsupported control character in JSON text")


def load_documents(paths):
    if not 1 <= len(paths) <= MAX_DOCUMENTS:
        raise InputError("provide 1 to 128 local JSON documents")
    documents, sources = [], []
    total = 0
    for filename in paths:
        path = Path(filename)
        try:
            with path.open("rb") as stream:
                data = stream.read(MAX_BYTES + 1)
            total += len(data)
            if len(data) > MAX_BYTES or total > MAX_TOTAL:
                raise InputError("input exceeds 8 MiB per document or 64 MiB total")
            document = json.loads(
                data.decode("utf-8-sig"), object_pairs_hook=_pairs, parse_constant=_constant
            )
            if not isinstance(document, dict):
                raise InputError("each JSON document must be an object")
            list(walk(document))
        except (OSError, UnicodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
            raise InputError(f"{path.name}: {exc}") from exc
        documents.append(document)
        sources.append({"file": path.name, "sha256": hashlib.sha256(data).hexdigest()})
    return documents, sources


def language_map(value):
    if not isinstance(value, dict) or not value:
        raise InputError("label/attribution must be a nonempty IIIF language map")
    result = []
    for language, texts in value.items():
        if not LANG.fullmatch(language) or not isinstance(texts, list) or not texts:
            raise InputError("invalid language map")
        for text in texts:
            if not isinstance(text, str) or not text.strip():
                raise InputError("language map values must be nonempty strings")
            result.append({"language": "" if language == "none" else language, "text": text})
    return result


def choose_label(value, language):
    entries = language_map(value)
    preferences = [language.lower()]
    while "-" in preferences[-1]:
        preferences.append(preferences[-1].rsplit("-", 1)[0])
    preferences.append("")
    for preference in preferences:
        matching = [x for x in entries if x["language"].lower() == preference]
        if matching:
            return {
                "text": " / ".join(x["text"] for x in matching),
                "language": matching[0]["language"],
            }
    first = sorted(entries, key=lambda x: x["language"])[0]
    return choose_label(
        {
            first["language"] or "none": [
                x["text"] for x in entries if x["language"] == first["language"]
            ]
        },
        first["language"],
    )


def _array(obj, key, default=None):
    value = obj.get(key, default)
    if not isinstance(value, list):
        raise InputError(f"{key} must be an array")
    return value


def _complete(obj):
    kind = obj.get("type")
    if not isinstance(kind, str) or kind not in FULL:
        return False
    if kind == "Canvas":
        return any(key in obj for key in ("annotations", "items", "width", "duration"))
    return FULL[kind] in obj


def target_uri(target):
    if isinstance(target, str):
        return http_uri(target)
    if not isinstance(target, dict) or target.get("type") != "SpecificResource":
        raise InputError("unsupported annotation target (expected URI or SpecificResource)")
    source = target.get("source")
    source = source.get("id") if isinstance(source, dict) else source
    source = http_uri(source)
    selector = target.get("selector")
    if selector is None:
        return source
    if (
        not isinstance(selector, dict)
        or selector.get("type") != "FragmentSelector"
        or not isinstance(selector.get("value"), str)
        or not selector["value"]
        or "refinedBy" in selector
        or "#" in source
    ):
        raise InputError("only unrefined FragmentSelector targets are supported")
    return http_uri(source + "#" + selector["value"])


def collect(documents, sources=None, language="en"):
    """Collect supplementing plain text in manifest/page/annotation array order."""
    if not documents or not LANG.fullmatch(language):
        raise InputError("missing manifest or invalid preferred label language")
    index = {}
    for document in documents:
        for obj in walk(document):
            if _complete(obj):
                identity = http_uri(obj.get("id"))
                if identity in index and index[identity] != obj:
                    raise InputError(f"conflicting full definitions of resource {identity!r}")
                index[identity] = obj
    manifest = documents[0]
    if manifest.get("type") != "Manifest" or "items" not in manifest:
        raise InputError("first document must be an embedded Presentation 3 Manifest")
    manifest_id = http_uri(manifest.get("id"))
    title = choose_label(manifest.get("label"), language)
    omissions, attributions, pages = [], [], []
    recorded = set()
    excluded = 0

    def issue(code, resource, detail):
        omissions.append({"code": code, "resource": resource, "detail": detail})

    def record(obj):
        # Retain attribution on every consumed resource, including referenced stubs.
        if "id" in obj:
            http_uri(obj["id"])
        statement, rights = obj.get("requiredStatement"), obj.get("rights")
        if statement is not None:
            if not isinstance(statement, dict):
                raise InputError("requiredStatement must be an object")
            label, value = (
                language_map(statement.get("label")),
                language_map(statement.get("value")),
            )
        else:
            label, value = [], []
        if rights is not None and not isinstance(rights, str):
            raise InputError("rights must be a string")
        item = {
            "resource": obj.get("id", "inline body"),
            "label": label,
            "value": value,
            "rights": rights,
        }
        key = json.dumps(item, sort_keys=True)
        if (statement is not None or rights is not None) and key not in recorded:
            recorded.add(key)
            attributions.append(item)

    def resolve(obj, kind):
        if not isinstance(obj, dict) or obj.get("type") != kind:
            raise InputError(f"expected a {kind} object")
        identity = http_uri(obj.get("id"))
        record(obj)
        result = obj if _complete(obj) else index.get(identity)
        if result is None:
            issue("missing_resource", identity, f"Supply the local {kind} JSON with --resource.")
            return None
        if result.get("type") != kind:
            raise InputError("referenced resource has a conflicting type")
        record(result)
        return result

    record(manifest)
    canvases = _array(manifest, "items")
    if not canvases:
        raise InputError("Manifest has no canvases")
    seen_canvases = set()
    for canvas_ref in canvases:
        canvas = resolve(canvas_ref, "Canvas")
        identity = canvas_ref["id"]
        if identity in seen_canvases or "#" in identity:
            raise InputError("duplicate Canvas ID or Canvas ID with a fragment")
        seen_canvases.add(identity)
        if canvas is None:
            pages.append({"id": identity, "label": {"text": identity, "language": ""}, "texts": []})
            continue
        page = {"id": identity, "label": choose_label(canvas.get("label"), language), "texts": []}
        pages.append(page)
        seen_pages, seen_annotations = set(), set()
        pending = list(reversed(_array(canvas, "annotations", [])))
        while pending:
            annotation_page_ref = pending.pop()
            annotation_page = resolve(annotation_page_ref, "AnnotationPage")
            if annotation_page is None:
                continue
            page_id = annotation_page["id"]
            if page_id in seen_pages:
                issue("repeated_page", page_id, "Repeated or cyclic annotation page reference.")
                continue
            seen_pages.add(page_id)
            for annotation_ref in _array(annotation_page, "items"):
                annotation = resolve(annotation_ref, "Annotation")
                if annotation is None:
                    continue
                anno_id = annotation["id"]
                if anno_id in seen_annotations:
                    issue("repeated_annotation", anno_id, "Repeated annotation was not duplicated.")
                    continue
                seen_annotations.add(anno_id)
                motivations = annotation.get("motivation", [])
                motivations = [motivations] if isinstance(motivations, str) else motivations
                if not isinstance(motivations, list) or not all(
                    isinstance(m, str) for m in motivations
                ):
                    raise InputError("motivation must be a string or array of strings")
                if "supplementing" not in motivations:
                    excluded += 1
                    continue
                try:
                    target = target_uri(annotation.get("target"))
                except InputError as exc:
                    issue("unsupported_target", anno_id, str(exc))
                    continue
                if target.split("#", 1)[0] != identity:
                    issue(
                        "different_canvas", anno_id, "Target does not match its containing Canvas."
                    )
                    continue
                bodies = annotation.get("body")
                bodies = bodies if isinstance(bodies, list) else [bodies]
                if not bodies:
                    issue("empty_body", anno_id, "Annotation has no bodies.")
                for body in bodies:
                    if isinstance(body, dict):
                        record(body)
                    if (
                        not isinstance(body, dict)
                        or body.get("type") != "TextualBody"
                        or body.get("format", "text/plain") != "text/plain"
                        or not isinstance(body.get("value"), str)
                        or not body["value"].strip()
                    ):
                        issue(
                            "unsupported_body",
                            anno_id,
                            "Only nonempty inline TextualBody values in text/plain are exported.",
                        )
                        continue
                    body_lang = body.get("language", "")
                    if not isinstance(body_lang, str) or (
                        body_lang and not LANG.fullmatch(body_lang)
                    ):
                        issue(
                            "unsupported_language",
                            anno_id,
                            "Body language must be one language tag.",
                        )
                        continue
                    page["texts"].append(
                        {
                            "annotation": anno_id,
                            "target": target,
                            "language": body_lang,
                            "text": body["value"],
                        }
                    )
            nxt = annotation_page.get("next")
            if nxt is not None:
                pending.append(
                    {"id": nxt, "type": "AnnotationPage"} if isinstance(nxt, str) else nxt
                )
        if not page["texts"]:
            issue("canvas_without_text", identity, "No supported supplementing text was collected.")

    return {
        "schema_version": 1,
        "manifest": manifest_id,
        "title": title,
        "summary": {
            "canvases": len(pages),
            "texts": sum(len(p["texts"]) for p in pages),
            "omissions": len(omissions),
            "excluded_non_supplementing": excluded,
        },
        "complete_within_supported_scope": not omissions,
        "pages": pages,
        "attributions": attributions,
        "omissions": omissions,
        "sources": sources or [],
        "ordering": (
            "Manifest canvas order, annotation page order, then annotation/body array order."
        ),
    }
