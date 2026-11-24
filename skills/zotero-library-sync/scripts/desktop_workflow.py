"""Prepare a local Zotero sync job or export a Word draft with live fields."""

import argparse
import csv
import json
import re
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from xml.etree import ElementTree


EVIDENCE = re.compile(r"\bE\d{3,}\b")
PARENTHETICAL = re.compile(r"\(([^()\n]*\bE\d{3,}\b[^()\n]*)\)")


def rows(path, delimiter=","):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream, delimiter=delimiter))


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def walk(node):
    if isinstance(node, dict):
        yield node
        for child in node.values():
            yield from walk(child)
    elif isinstance(node, list):
        for child in node:
            yield from walk(child)


def pandoc(executable, *args, cwd, source):
    result = subprocess.run([executable, *map(str, args)], input=source, cwd=cwd, capture_output=True)
    if result.returncode or result.stderr:
        raise ValueError(result.stderr.decode("utf-8", "replace").strip() or "Pandoc failed")
    return result.stdout


def citation_keys(ast):
    return list(dict.fromkeys(
        item["citationId"]
        for node in walk(ast["blocks"]) if node.get("t") == "Cite"
        for item in node["c"][0]
    ))


def check_citation_forms(ast):
    for node in walk(ast["blocks"]):
        if node.get("t") == "Cite":
            for item in node["c"][0]:
                if item["citationPrefix"] or item["citationSuffix"] or item["citationMode"]["t"] != "NormalCitation":
                    raise ValueError(f"Unsupported live citation form: {item['citationId']}")


def normalize_citations(markdown, evidence):
    def convert(match):
        # A project citation consists of one or more author-year / evidence-ID pairs.
        chunks = [chunk.strip() for chunk in match[1].split(";")]
        if not all(
            EVIDENCE.fullmatch(chunk) or re.fullmatch(r"[^;]+,\s*\d{4}[a-z]?", chunk)
            for chunk in chunks
        ) or any(
            not EVIDENCE.fullmatch(chunk) and
            (index + 1 == len(chunks) or not EVIDENCE.fullmatch(chunks[index + 1]))
            for index, chunk in enumerate(chunks)
        ):
            raise ValueError(f"Express this citation as Pandoc citations before exporting: {match[0]}")
        keys = dict.fromkeys(evidence[chunk]["citation_key"] for chunk in chunks if EVIDENCE.fullmatch(chunk))
        return "[" + "; ".join("@" + key for key in keys) + "]"

    converted = PARENTHETICAL.sub(convert, markdown)
    if EVIDENCE.search(converted):
        raise ValueError("Unresolved evidence identifiers. Normalize citations in the export input.")
    return converted


def target_rows(project, mode, keys=(), evidence_rows=()):
    library = {row["record_id"]: row for row in rows(project / "02-records/library.csv")}
    if mode == "archive":
        selected = rows(project / "03-screening/included.tsv", "\t")
    else:
        by_key = {}
        for row in evidence_rows:
            previous = by_key.setdefault(row["citation_key"], row)
            if row["citation_key"] in keys and previous["record_id"] != row["record_id"]:
                raise ValueError(f"Ambiguous evidence key: {row['citation_key']}")
        selected = [by_key[key] for key in keys]
    result = []
    for row in selected:
        record = library[row["record_id"]]
        result.append({
            "record_id": row["record_id"],
            "citation_key": row["citation_key"],
            **{field: (record.get(field) or row.get(field) or "").strip()
               for field in ("doi", "pmid", "title", "year")},
        })
    if not result or any(not row["citation_key"] or not row["title"] for row in result):
        raise ValueError("Expected at least one target and a citation key and title for each target")
    return result


def prepare(args):
    project = args.project.resolve()
    if args.mode == "archive":
        if args.source:
            raise ValueError("--source is for Word mode")
        targets = target_rows(project, args.mode)
    else:
        if not args.source:
            raise ValueError("Word mode requires the assembled --source including all cited figure and table content")
        source = args.source.resolve()
        evidence = rows(project / "evidence/evidence_table.csv")
        markdown = normalize_citations(
            source.read_text(encoding="utf-8-sig"), {row["evidence_id"]: row for row in evidence}
        )
        ast = json.loads(pandoc(args.pandoc, "-f", "markdown", "-t", "json",
                               cwd=source.parent, source=markdown.encode("utf-8")))
        check_citation_forms(ast)
        targets = target_rows(project, args.mode, citation_keys(ast), evidence)

    folder = args.job.resolve()
    folder.mkdir(parents=True, exist_ok=False)
    config = {"collection": args.collection, "targets": targets}
    write_json(folder / "targets.json", config)
    if args.mode == "word":
        write_json(folder / "source.json", {"directory": str(source.parent), "document": ast})
    code = Path(__file__).with_name("sync_desktop.js").read_text(encoding="utf-8")
    job = json.dumps(config)
    mapping = json.dumps((folder / "mapping.json").as_posix())
    (folder / "run-in-zotero.js").write_text(
        f"{code}\nconst result = await syncCollection({job}, Zotero);\n"
        f"await Zotero.File.putContentsAsync({mapping}, JSON.stringify(result, null, 2));\n"
        "return JSON.stringify({collection: result.collection, mapped: result.mappings.length, failures: result.failures});\n",
        encoding="utf-8",
    )
    print(f"Prepared {len(targets)} targets in {folder}")


def live_entries(folder, document):
    config = read_json(folder / "targets.json")
    mapping = read_json(folder / "mapping.json")
    entries = {entry["citation_key"]: entry for entry in mapping["mappings"]}
    expected = {row["citation_key"]: row["record_id"] for row in config["targets"]}
    if (mapping["failures"] or mapping["collection"] != config["collection"]
            or len(entries) != len(mapping["mappings"]) or set(expected) != set(citation_keys(document))
            or expected != {key: entry["record_id"] for key, entry in entries.items()}
            or any(not entry["uri"] or entry["csl"]["id"] != key for key, entry in entries.items())):
        raise ValueError("Zotero mapping is incomplete or inconsistent. Dynamic Word export is pending.")
    return mapping["zotero_version"], entries


def export(args):
    from live_word_fields import add_bibliography_field, add_citation_fields, open_with_preferences

    folder = args.job.resolve()
    prepared = read_json(folder / "source.json")
    document = prepared["document"]
    directory = Path(prepared["directory"])
    version, entries = live_entries(folder, document)
    style = args.csl.resolve()
    style_metadata = ElementTree.parse(style)
    if style_metadata.getroot().get("class") == "note":
        raise ValueError("Note-based CSL styles require citation insertion in the Word plugin")
    style_id = style_metadata.findtext("{*}info/{*}id")
    if not style_id:
        raise ValueError("CSL lacks a style ID")
    if args.output.exists():
        raise ValueError("Choose a new output path to preserve any existing Word draft")
    with TemporaryDirectory() as tmp:
        scratch = Path(tmp)
        bibliography = scratch / "references.json"
        write_json(bibliography, [entry["csl"] for entry in entries.values()])
        rendered = json.loads(pandoc(
            args.pandoc, "-f", "json", "-t", "json", "--citeproc", "--bibliography", bibliography,
            "--csl", style, cwd=directory, source=json.dumps(document).encode("utf-8"),
        ))
        rendered["blocks"] = add_citation_fields(rendered["blocks"], entries)
        add_bibliography_field(rendered["blocks"])
        body = scratch / "body.docx"
        extra = ["--reference-doc", args.reference_doc.resolve()] if args.reference_doc else []
        pandoc(args.pandoc, "-f", "json", "-o", body, *extra, cwd=directory,
               source=json.dumps(rendered).encode("utf-8"))
        draft = open_with_preferences(body, version, style_id)
        with args.output.open("xb") as stream:
            draft.save(stream)
    print(f"Generated {args.output}. Word Refresh verification is pending.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prep = commands.add_parser("prepare")
    prep.add_argument("--mode", choices=("archive", "word"), required=True)
    prep.add_argument("--project", type=Path, required=True)
    prep.add_argument("--collection", required=True)
    prep.add_argument("--source", type=Path)
    build = commands.add_parser("export")
    build.add_argument("--csl", type=Path, required=True)
    build.add_argument("--reference-doc", type=Path)
    build.add_argument("--output", type=Path, required=True)
    for command in (prep, build):
        command.add_argument("--job", type=Path, required=True)
        command.add_argument("--pandoc", default="pandoc")
    args = parser.parse_args(argv)
    try:
        (prepare if args.command == "prepare" else export)(args)
    except (OSError, ValueError, KeyError, ImportError, ElementTree.ParseError) as error:
        print(f"ERROR {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
