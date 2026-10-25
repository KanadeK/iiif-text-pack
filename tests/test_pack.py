import copy
import json
import os
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

import pytest

from iiif_text_pack import core
from iiif_text_pack.core import InputError, choose_label, collect, http_uri, load_documents
from iiif_text_pack.render import html_document, plain_text, write_pack

BASE = "https://collection.example/"


def annotation(identity="a1", value="First line\nSecond line", target=BASE + "c1", **kwargs):
    return {
        "id": BASE + identity,
        "type": "Annotation",
        "motivation": "supplementing",
        "body": {"type": "TextualBody", "value": value, "language": "en"},
        "target": target,
        **kwargs,
    }


def manifest():
    return {
        "id": BASE + "manifest",
        "type": "Manifest",
        "label": {"en": ["A notebook"]},
        "items": [
            {
                "id": BASE + "c1",
                "type": "Canvas",
                "width": 100,
                "height": 200,
                "label": {"en": ["Page one"]},
                "annotations": [
                    {"id": BASE + "p1", "type": "AnnotationPage", "items": [annotation()]}
                ],
            }
        ],
    }


def codes(report):
    return {x["code"] for x in report["omissions"]}


def test_complete_pack_has_order_and_provenance():
    doc = manifest()
    page = doc["items"][0]["annotations"][0]
    page["items"].append(annotation("a2", "Later paragraph", BASE + "c1#xywh=0,0,50,20"))
    report = collect([doc])
    assert report["complete_within_supported_scope"]
    assert report["summary"] == {
        "canvases": 1,
        "texts": 2,
        "omissions": 0,
        "excluded_non_supplementing": 0,
    }
    assert [x["text"] for x in report["pages"][0]["texts"]] == [
        "First line\nSecond line",
        "Later paragraph",
    ]
    assert report["pages"][0]["texts"][1]["target"].endswith("#xywh=0,0,50,20")
    assert "Annotation: " + BASE + "a2" in plain_text(report)


def test_external_page_annotation_and_pagination_resolution():
    doc = manifest()
    external = doc["items"][0]["annotations"][0]
    anno = external["items"][0]
    external["items"] = [{"id": anno["id"], "type": "Annotation"}]
    external["next"] = BASE + "p2"
    next_page = {"id": BASE + "p2", "type": "AnnotationPage", "items": [annotation("a2", "Next")]}
    doc["items"][0]["annotations"] = [{"id": external["id"], "type": "AnnotationPage"}]
    report = collect([doc, external, anno, next_page])
    assert report["summary"]["texts"] == 2
    assert not report["omissions"]


def test_missing_resources_and_cycles_are_explicit():
    doc = manifest()
    page = doc["items"][0]["annotations"][0]
    page["next"] = page["id"]
    assert "repeated_page" in codes(collect([doc]))
    page["next"] = BASE + "missing"
    assert "missing_resource" in codes(collect([doc]))
    doc["items"][0]["annotations"] = [{"id": BASE + "missing", "type": "AnnotationPage"}]
    assert codes(collect([doc])) == {"missing_resource", "canvas_without_text"}


def test_duplicate_annotations_are_not_repeated():
    doc = manifest()
    page = doc["items"][0]["annotations"][0]
    page["items"].append(copy.deepcopy(page["items"][0]))
    report = collect([doc])
    assert report["summary"]["texts"] == 1
    assert codes(report) == {"repeated_annotation"}


def test_wrong_canvas_and_selectors():
    doc = manifest()
    anno = doc["items"][0]["annotations"][0]["items"][0]
    anno["target"] = {
        "type": "SpecificResource",
        "source": {"id": BASE + "c1"},
        "selector": {"type": "FragmentSelector", "value": "xywh=0,0,10,10"},
    }
    report = collect([doc])
    assert not report["omissions"]
    assert report["pages"][0]["texts"][0]["target"] == BASE + "c1#xywh=0,0,10,10"
    anno["target"]["selector"]["type"] = "SvgSelector"
    assert "unsupported_target" in codes(collect([doc]))
    anno["target"] = BASE + "c2"
    assert "different_canvas" in codes(collect([doc]))


@pytest.mark.parametrize(
    "body",
    [
        {"type": "Text", "id": BASE + "text.txt", "format": "text/plain"},
        {"type": "TextualBody", "value": "<p>HTML</p>", "format": "text/html"},
        {"type": "Choice", "items": []},
        None,
        "remote",
        {"type": "TextualBody", "value": ""},
        {"type": "TextualBody", "value": 12},
        [],
    ],
)
def test_unsupported_bodies_never_silently_pass(body):
    doc = manifest()
    doc["items"][0]["annotations"][0]["items"][0]["body"] = body
    assert collect([doc])["omissions"]


def test_all_body_languages_preserved_but_label_language_selected():
    doc = manifest()
    doc["label"] = {"fr": ["Carnet"], "en": ["Notebook"]}
    anno = doc["items"][0]["annotations"][0]["items"][0]
    anno["body"] = [
        {"type": "TextualBody", "value": "Bonjour", "language": "fr"},
        {"type": "TextualBody", "value": "你好", "language": "zh-Hans"},
    ]
    report = collect([doc], language="fr-CA")
    assert report["title"]["text"] == "Carnet"
    assert [x["language"] for x in report["pages"][0]["texts"]] == ["fr", "zh-Hans"]
    assert 'lang="zh-Hans"' in html_document(report)
    anno["body"][0]["language"] = ["fr", "en"]
    assert "unsupported_language" in codes(collect([doc]))


def test_non_supplementing_excluded_with_count():
    doc = manifest()
    doc["items"][0]["annotations"][0]["items"].append(annotation("a2", motivation="commenting"))
    report = collect([doc])
    assert not report["omissions"]
    assert report["summary"]["excluded_non_supplementing"] == 1


def test_attribution_retained_on_every_consumed_level():
    doc = manifest()
    resources = [
        doc,
        doc["items"][0],
        doc["items"][0]["annotations"][0],
        doc["items"][0]["annotations"][0]["items"][0],
    ]
    resources.append(resources[-1]["body"])
    for i, resource in enumerate(resources):
        resource["requiredStatement"] = {
            "label": {"en": ["Credit"]},
            "value": {"en": [f"Credit {i}"]},
        }
    doc["rights"] = "https://creativecommons.org/publicdomain/zero/1.0/"
    report = collect([doc])
    assert len(report["attributions"]) == 5
    for i in range(5):
        assert f"Credit {i}" in html_document(report)
        assert f"Credit {i}" in plain_text(report)


class Markup(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags, self.links, self.ids, self.data = [], [], [], []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        attrs = dict(attrs)
        if "href" in attrs:
            self.links.append(attrs["href"])
        if "id" in attrs:
            self.ids.append(attrs["id"])
        assert not any(k.lower().startswith("on") for k in attrs)

    def handle_data(self, data):
        self.data.append(data)


def test_html_payloads_are_literal_no_remote_assets_or_scripts():
    doc = manifest()
    payload = '<script>alert("x")</script><img src="https://evil.example/pixel"> & text'
    doc["label"] = {"en": [payload]}
    doc["items"][0]["annotations"][0]["items"][0]["body"]["value"] = payload
    doc["rights"] = "javascript:alert(1)"
    rendered = html_document(collect([doc]))
    parsed = Markup()
    parsed.feed(rendered)
    assert not {"script", "img", "iframe", "object", "form"} & set(parsed.tags)
    assert not any(x.startswith("javascript:") for x in parsed.links)
    assert payload in parsed.data
    assert len(parsed.ids) == len(set(parsed.ids))
    assert all(x[1:] in parsed.ids for x in parsed.links if x.startswith("#"))


def test_existing_output_and_default_partial_refusal(tmp_path):
    report = collect([manifest()])
    destination = tmp_path / "pack"
    write_pack(report, destination)
    before = (destination / "index.html").read_bytes()
    with pytest.raises(InputError):
        write_pack(report, destination)
    assert (destination / "index.html").read_bytes() == before
    report["omissions"] = [
        {"code": "missing_resource", "resource": BASE + "missing", "detail": "Missing"}
    ]
    with pytest.raises(InputError):
        write_pack(report, tmp_path / "refused")
    assert not (tmp_path / "refused").exists()
    write_pack(report, tmp_path / "partial", allow_partial=True)
    assert "Partial reading pack" in (tmp_path / "partial/index.html").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "raw",
    [
        b'{"type":"Manifest","type":"Canvas"}',
        b'{"value":NaN}',
        b"[]",
        b"not json",
        b"\xff",
        b'{"s":"\\ud800"}',
        b'{"s":"\\u0000"}',
    ],
)
def test_bad_json(tmp_path, raw):
    p = tmp_path / "input.json"
    p.write_bytes(raw)
    with pytest.raises(InputError):
        load_documents([p])


@pytest.mark.parametrize(
    "uri",
    [
        None,
        "javascript:alert(1)",
        "file:///x",
        "/local",
        "https://u:p@example.com/x",
        "https://e.test/\nfoo",
        "https://e.test/\\foo",
        "https://[broken/",
    ],
)
def test_unsafe_or_unsupported_ids(uri):
    with pytest.raises(InputError):
        http_uri(uri)


def test_structural_errors_and_conflicts():
    with pytest.raises(InputError):
        collect([{"type": "Collection"}])
    doc = manifest()
    conflict = copy.deepcopy(doc["items"][0]["annotations"][0])
    conflict["items"][0]["body"]["value"] = "conflict"
    with pytest.raises(InputError, match="conflicting"):
        collect([doc, conflict])
    doc["items"].append(copy.deepcopy(doc["items"][0]))
    with pytest.raises(InputError, match="duplicate Canvas"):
        collect([doc])
    doc = manifest()
    doc["requiredStatement"] = {"label": {"en": ["Attribution"]}}
    with pytest.raises(InputError):
        collect([doc])


def test_bounds_and_language_fallbacks(tmp_path, monkeypatch):
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps(manifest()), encoding="utf-8")
    docs, sources = load_documents([p])
    assert len(sources[0]["sha256"]) == 64 and docs[0] == manifest()
    monkeypatch.setattr(core, "MAX_BYTES", 5)
    with pytest.raises(InputError):
        load_documents([p])
    nested = value = {}
    for _ in range(70):
        value["nested"] = {}
        value = value["nested"]
    with pytest.raises(InputError, match="depth"):
        list(core.walk(nested))
    assert choose_label({"none": ["One", "Two"]}, "en")["text"] == "One / Two"
    assert choose_label({"zh": ["标题"], "fr": ["Titre"]}, "en")["text"] == "Titre"


def test_cli_complete_and_partial_workflow(tmp_path):
    doc = manifest()
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).parents[1] / "src"))

    def run(*args):
        return subprocess.run(
            [sys.executable, "-m", "iiif_text_pack", str(p), *args],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

    result = run("--output", str(tmp_path / "complete"))
    assert result.returncode == 0 and json.loads(result.stdout)["written"]
    assert (tmp_path / "complete/text.txt").is_file()
    assert run("--output", str(tmp_path / "complete")).returncode == 2
    doc["items"][0]["annotations"] = [{"id": BASE + "missing", "type": "AnnotationPage"}]
    p.write_text(json.dumps(doc), encoding="utf-8")
    result = run("--output", str(tmp_path / "blocked"))
    assert result.returncode == 1 and not (tmp_path / "blocked").exists()
    result = run("--output", str(tmp_path / "partial"), "--allow-partial")
    assert result.returncode == 1 and json.loads(result.stdout)["written"]
    assert run("--check").returncode == 1


def test_library_does_not_mutate_inputs():
    original = manifest()
    copy_of_original = copy.deepcopy(original)
    collect([original])
    assert original == copy_of_original


def test_invalid_inline_body_id_is_reported_as_input_error():
    doc = manifest()
    body = doc["items"][0]["annotations"][0]["items"][0]["body"]
    body["id"] = {"not": "an identifier"}
    body["requiredStatement"] = {"label": {"en": ["Credit"]}, "value": {"en": ["Owner"]}}
    with pytest.raises(InputError):
        collect([doc])


@pytest.mark.parametrize("uri", ["https://@example.org/x", "https://example.org:bad/x"])
def test_invalid_authority(uri):
    with pytest.raises(InputError):
        http_uri(uri)


@pytest.mark.parametrize(
    "path",
    [
        ["label"],
        ["items"],
        ["items", 0, "annotations"],
        ["items", 0, "annotations", 0, "items"],
        ["items", 0, "annotations", 0, "items", 0, "motivation"],
        ["items", 0, "annotations", 0, "items", 0, "target"],
        ["items", 0, "annotations", 0, "items", 0, "body"],
    ],
)
def test_wrong_json_value_types_do_not_crash(path):
    for value in (None, True, 7, "x", [], {}, [{"unexpected": "value"}]):
        doc = manifest()
        node = doc
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = value
        try:
            report = collect([doc])
        except InputError:
            continue
        assert isinstance(report, dict) and "omissions" in report
