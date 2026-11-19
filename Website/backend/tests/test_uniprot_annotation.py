import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uniprot_annotation import AnnotationService, default_annotation_dir  # noqa: E402

HEADER = ("Entry\tEntry Name\tGene Names\tOrganism\tFunction [CC]\tProtein names\t"
          "Gene Names (ordered locus)\tOrganism (ID)\tPathway\n")


def write(tmp_path, name, rows):
    (tmp_path / name).write_text(HEADER + "".join("\t".join(r) + "\n" for r in rows))


def test_match_notfound_ambiguous_and_organism(tmp_path):
    write(tmp_path, "a.tsv", [
        ["P1", "X_A", "abc ORG_1", "Org A", "FUNCTION: x.", "Prot 1", "ORG_1", "11", ""],
        ["P2", "X_B", "", "Org A", "", "Prot 2", "ORG_2 ORG_3", "11", ""],
        ["P3", "X_C", "", "Org A", "", "Prot 3", "ORG_3", "11", ""],
    ])
    write(tmp_path, "b.tsv", [
        ["Q1", "Y_A", "", "Org B", "", "Other", "ORG_1", "22", "PATHWAY: y."],
    ])
    svc = AnnotationService(str(tmp_path))
    assert svc.lookup("ORG_1")["status"] == "ambiguous"
    r = svc.lookup("ORG_1", organism="Org A")
    assert r["status"] == "matched" and r["annotation"]["accession"] == "P1"
    assert r["annotation"]["function"] == "FUNCTION: x."
    assert r["annotation"]["pathway"] is None
    assert svc.lookup("ORG_1", organism="22")["annotation"]["accession"] == "Q1"
    assert svc.lookup("ORG_2")["annotation"]["accession"] == "P2"
    assert svc.lookup("ORG_3")["status"] == "ambiguous"
    assert svc.lookup("ORG_9")["status"] == "not_found"


def test_real_salmonella_file():
    svc = AnnotationService(default_annotation_dir())
    if not svc.discover_files():
        return
    r = svc.lookup("SL1344_0458")
    assert r["status"] == "matched"
    assert r["annotation"]["accession"] == "A0A0H3N904"
