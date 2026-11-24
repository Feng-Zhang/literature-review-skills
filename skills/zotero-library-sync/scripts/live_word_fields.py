"""Encode Zotero fields using Pandoc's rendered citation and bibliography text."""

from html import escape
import json
from uuid import uuid4

from docx import Document
from docx.opc.part import Part
from docx.opc.packuri import PackURI
from lxml import etree


SCHEMA = "https://github.com/citation-style-language/schema/raw/master/csl-citation.json"


def raw_inline(xml):
    return {"t": "RawInline", "c": ["openxml", xml]}


def start_field(instruction):
    return ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            '<w:r><w:instrText xml:space="preserve">' + escape(" " + instruction + " ") +
            '</w:instrText></w:r><w:r><w:fldChar w:fldCharType="separate"/></w:r>')


END_FIELD = '<w:r><w:fldChar w:fldCharType="end"/></w:r>'


def add_citation_fields(ast, entries):
    """Wrap CSL-rendered citation results with the corresponding Zotero instruction."""
    if isinstance(ast, list):
        rewritten = []
        for node in ast:
            if isinstance(node, dict) and node.get("t") == "Cite":
                items, display = node["c"]
                citation_items = []
                for item in items:
                    entry = entries[item["citationId"]]
                    citation_items.append({
                        "id": entry["item_id"], "uris": [entry["uri"]],
                        "itemData": {**entry["csl"], "id": entry["item_id"]},
                    })
                payload = {
                    "citationID": uuid4().hex[:8], "properties": {"noteIndex": 0},
                    "citationItems": citation_items, "schema": SCHEMA,
                }
                code = "ADDIN ZOTERO_ITEM CSL_CITATION " + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
                rewritten.extend([raw_inline(start_field(code)), *display, raw_inline(END_FIELD)])
            else:
                rewritten.append(add_citation_fields(node, entries))
        return rewritten
    if isinstance(ast, dict):
        return {key: add_citation_fields(value, entries) for key, value in ast.items()}
    return ast


def add_bibliography_field(blocks):
    bibliography = next((node["c"][1] for node in blocks
                         if node.get("t") == "Div" and node["c"][0][0] == "refs"), None)
    if not bibliography:
        raise ValueError("Pandoc did not generate a bibliography")
    first = bibliography[0]["c"][1][0]
    last = bibliography[-1]["c"][1][-1]
    if any(node["t"] not in ("Para", "Plain") for node in (first, last)):
        raise ValueError("Unexpected Pandoc bibliography structure")
    code = 'ADDIN ZOTERO_BIBL {"uncited":[],"omitted":[],"custom":[]} CSL_BIBLIOGRAPHY'
    first["c"].insert(0, raw_inline(start_field(code)))
    last["c"].append(raw_inline(END_FIELD))


def open_with_preferences(path, version, style_id):
    doc = Document(path)
    set_zotero_preferences(doc, version, style_id)
    return doc


def set_zotero_preferences(doc, zotero_version, style_id):
    data = (
        f'<data data-version="3" zotero-version="{escape(zotero_version)}">'
        f'<session id="{uuid4().hex[:8]}"/>'
        f'<style id="{escape(style_id, quote=True)}" locale="en-US" '
        'hasBibliography="1" bibliographyStyleHasBeenSet="0"/>'
        '<prefs><pref name="fieldType" value="Field"/>'
        '<pref name="automaticJournalAbbreviations" value="false"/>'
        '<pref name="delayCitationUpdates" value="false"/></prefs></data>'
    )
    relationship = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/custom-properties"
    custom = "http://schemas.openxmlformats.org/officeDocument/2006/custom-properties"
    types = "http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"
    package = doc.part.package
    try:
        part = package.part_related_by(relationship)
    except KeyError:
        part = None
    root = etree.fromstring(part.blob) if part else etree.Element(
        f"{{{custom}}}Properties", nsmap={None: custom, "vt": types}
    )
    for entry in list(root):
        if entry.get("name", "").startswith("ZOTERO_PREF_"):
            root.remove(entry)
    pid = max([1, *(int(entry.get("pid", "1")) for entry in root)])
    for index, offset in enumerate(range(0, len(data), 255), 1):
        entry = etree.SubElement(
            root, f"{{{custom}}}property", fmtid="{D5CDD505-2E9C-101B-9397-08002B2CF9AE}",
            pid=str(pid + index), name=f"ZOTERO_PREF_{index}",
        )
        etree.SubElement(entry, f"{{{types}}}lpwstr").text = data[offset:offset + 255]
    xml = etree.tostring(root, encoding="utf-8")
    if part:
        part._blob = xml
    else:
        part = Part(PackURI("/docProps/custom.xml"),
                    "application/vnd.openxmlformats-officedocument.custom-properties+xml", xml)
        package.relate_to(part, relationship)



