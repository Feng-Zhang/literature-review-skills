import json
import os
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory
import unittest
from xml.etree import ElementTree
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from desktop_workflow import main  # noqa: E402


PANDOC = os.environ.get("LRS_TEST_PANDOC") or shutil.which("pandoc")
CSL = """<style xmlns="http://purl.org/net/xbiblio/csl" class="in-text" version="1.0">
<info><title>LRS fixture</title><id>http://www.zotero.org/styles/lrs-fixture</id></info>
<citation><layout prefix="[" suffix="]" delimiter=","><text variable="citation-number"/></layout></citation>
<bibliography><layout><text variable="citation-number" suffix=". "/><text variable="title"/></layout></bibliography>
</style>"""


class DesktopWorkflowTest(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        for subdir in ("02-records", "03-screening", "evidence"):
            (self.root / subdir).mkdir()
        (self.root / "02-records/library.csv").write_text(
            "record_id,title,doi,pmid,year\nR1,Paper A,10.1234/a,,2020\n"
            "R2,Paper B,,123,2021\nR3,Paper C,,,2022\nR4,Paper D,,,2023\n", encoding="utf-8")
        (self.root / "03-screening/included.tsv").write_text(
            "record_id\tcitation_key\nR3\tC2022\nR4\tD2023\n", encoding="utf-8")
        (self.root / "evidence/evidence_table.csv").write_text(
            "evidence_id,record_id,citation_key\nE001,R1,A2020\nE002,R2,B2021\n"
            "E003,R3,C2022\nE004,R4,D2023\n", encoding="utf-8")

    def args(self, mode):
        return ["prepare", "--mode", mode, "--project", str(self.root),
                "--collection", "LRS temporary classification", "--job", str(self.root / "job")]

    def test_archive_uses_included_records_only(self):
        self.assertEqual(main(self.args("archive")), 0)
        targets = json.loads((self.root / "job/targets.json").read_text(encoding="utf-8"))["targets"]
        self.assertEqual([row["record_id"] for row in targets], ["R3", "R4"])

    @unittest.skipUnless(PANDOC, "Pandoc is required for the live DOCX integration test")
    def test_two_sections_caption_and_table_become_live_fields(self):
        manuscript = self.root / "manuscript.md"
        manuscript.write_text(
            "## Section one\n\nText (Smith, 2020; E001).\n\n"
            "## Section two\n\nText [@B2021].\n\n"
            "**Fig. 1.** Caption [@C2022].\n\n"
            "| Finding | Reference |\n|---|---|\n| Result | [@D2023] |\n", encoding="utf-8")
        (self.root / "alternative.md").write_text("Excluded [@Wrong2022]", encoding="utf-8")
        self.assertEqual(main(self.args("word") + ["--source", str(manuscript), "--pandoc", PANDOC]), 0)
        job = self.root / "job"
        config = json.loads((job / "targets.json").read_text(encoding="utf-8"))
        self.assertEqual([row["citation_key"] for row in config["targets"]], ["A2020", "B2021", "C2022", "D2023"])
        mapping = {"collection": config["collection"], "failures": [], "zotero_version": "8.0", "mappings": []}
        for index, row in enumerate(config["targets"], 1):
            mapping["mappings"].append({
                **row, "item_id": index, "uri": f"http://zotero.org/users/local/test/items/TEST{index}",
                "csl": {"id": row["citation_key"], "type": "article-journal", "title": row["title"]},
            })
        style = self.root / "sample.csl"
        style.write_text(CSL, encoding="utf-8")
        docx = self.root / "manuscript-zotero.docx"
        args = ["export", "--job", str(job), "--csl", str(style), "--output", str(docx), "--pandoc", PANDOC]
        (job / "mapping.json").write_text(json.dumps({**mapping, "mappings": mapping["mappings"][:-1]}))
        self.assertEqual(main(args), 1)
        self.assertFalse(docx.exists())
        (job / "mapping.json").write_text(json.dumps(mapping))
        self.assertEqual(main(args), 0)
        with ZipFile(docx) as package:
            ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            document = ElementTree.fromstring(package.read("word/document.xml"))
            instructions = [node.text for node in document.findall(".//w:instrText", ns)]
            self.assertEqual(sum("ZOTERO_ITEM" in code for code in instructions), 4)
            self.assertEqual(sum("ZOTERO_BIBL" in code for code in instructions), 1)
            self.assertIn(b"ZOTERO_PREF_", package.read("docProps/custom.xml"))


if __name__ == "__main__":
    unittest.main()
