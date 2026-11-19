"""Local UniProt annotation loading and locus-tag lookup (read-only).

Reads UniProt TSV exports stored in ``Website/annotation`` and builds an
in-memory index keyed by the ``Gene Names (ordered locus)`` identifiers.
Files are parsed once (lazily, on first lookup) and never modified. This
module is independent of the expression matrix and of all visualizations.

Directory resolution:
  1. ``MICROMIX_ANNOTATION_DIR`` environment variable, if set.
  2. ``<backend source dir>/../annotation`` (i.e. ``Website/annotation``).
"""

import csv
import os
import re
import threading

ANNOTATION_DIR_ENV = "MICROMIX_ANNOTATION_DIR"

# UniProt columns recognized by this service (all optional except the locus
# column, which is required for a file to be indexed).
COL_ENTRY = "Entry"
COL_ENTRY_NAME = "Entry Name"
COL_REVIEWED = "Reviewed"
COL_PROTEIN_NAMES = "Protein names"
COL_GENE_NAMES = "Gene Names"
COL_LOCUS = "Gene Names (ordered locus)"
COL_ORGANISM = "Organism"
COL_ORGANISM_ID = "Organism (ID)"
COL_FUNCTION = "Function [CC]"
COL_GO_BP = "Gene Ontology (biological process)"
COL_GO_CC = "Gene Ontology (cellular component)"
COL_GO_MF = "Gene Ontology (molecular function)"
COL_GO_ALL = "Gene Ontology (GO)"
COL_GO_IDS = "Gene Ontology IDs"
COL_CATALYTIC = "Catalytic activity"
COL_PATHWAY = "Pathway"

# Identifiers inside a UniProt multi-value gene field are whitespace
# separated; ';' and '/' also occur in some exports.
_ID_SPLIT = re.compile(r"[\s;/,]+")

STATUS_MATCHED = "matched"
STATUS_NOT_FOUND = "not_found"
STATUS_AMBIGUOUS = "ambiguous"


def default_annotation_dir():
    env = os.environ.get(ANNOTATION_DIR_ENV)
    if env:
        return os.path.abspath(env)
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(here, os.pardir, "annotation"))


def _clean(value):
    """Return the original text, or None for blank/missing fields."""
    if value is None:
        return None
    return value if value.strip() else None


def split_identifiers(value):
    if not value:
        return []
    return [tok for tok in _ID_SPLIT.split(value.strip()) if tok]


def _looks_like_uniprot_tsv(path):
    """True if the file's header line is a tab-separated UniProt header that
    contains the ordered-locus column. Used for discovery so that UniProt
    exports saved without a ``.tsv`` extension are still found."""
    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
            header = fh.readline().rstrip("\r\n").split("\t")
    except (OSError, UnicodeError):
        return False
    return COL_ENTRY in header and COL_LOCUS in header


class AnnotationService:
    def __init__(self, directory=None):
        self.directory = directory or default_annotation_dir()
        self._lock = threading.Lock()
        self._loaded = False
        self._records = []          # list of record dicts
        self._by_locus = {}         # locus tag -> list of record indices
        self._sources = []          # per-file load summaries
        self._errors = []

    # ------------------------------------------------------------------ load
    def discover_files(self):
        if not os.path.isdir(self.directory):
            return []
        found = []
        for name in sorted(os.listdir(self.directory)):
            path = os.path.join(self.directory, name)
            if name.startswith(".") or not os.path.isfile(path):
                continue
            ext = os.path.splitext(name)[1].lower()
            if ext == ".tsv" or (ext == "" and _looks_like_uniprot_tsv(path)):
                found.append(path)
        return found

    def ensure_loaded(self):
        if self._loaded:
            return
        with self._lock:
            if not self._loaded:
                self._load()
                self._loaded = True

    def reload(self):
        with self._lock:
            self._records, self._by_locus = [], {}
            self._sources, self._errors = [], []
            self._load()
            self._loaded = True

    def _load(self):
        for path in self.discover_files():
            try:
                self._load_file(path)
            except Exception as exc:  # keep other files usable
                self._errors.append({"file": os.path.basename(path),
                                     "error": f"{exc.__class__.__name__}: {exc}"})

    def _load_file(self, path):
        filename = os.path.basename(path)
        with open(path, "r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh, delimiter="\t", quoting=csv.QUOTE_NONE)
            columns = reader.fieldnames or []
            if COL_LOCUS not in columns:
                self._errors.append({"file": filename,
                                     "error": f"missing column '{COL_LOCUS}'"})
                return
            rows = 0
            for line_no, row in enumerate(reader, start=2):
                rows += 1
                record = self._make_record(row, filename, line_no)
                idx = len(self._records)
                self._records.append(record)
                for locus in record["locus_tags"]:
                    bucket = self._by_locus.setdefault(locus, [])
                    if idx not in bucket:
                        bucket.append(idx)
        self._sources.append({"file": filename, "rows": rows, "columns": columns})

    @staticmethod
    def _make_record(row, filename, line_no):
        get = lambda col: _clean(row.get(col))
        go_bp, go_cc, go_mf = get(COL_GO_BP), get(COL_GO_CC), get(COL_GO_MF)
        return {
            "accession": get(COL_ENTRY),
            "entry_name": get(COL_ENTRY_NAME),
            "reviewed": get(COL_REVIEWED),
            "protein_name": get(COL_PROTEIN_NAMES),
            "gene_names": get(COL_GENE_NAMES),
            "gene_names_list": split_identifiers(get(COL_GENE_NAMES)),
            "locus_tags": split_identifiers(get(COL_LOCUS)),
            "ordered_locus": get(COL_LOCUS),
            "organism": get(COL_ORGANISM),
            "organism_id": get(COL_ORGANISM_ID),
            "function": get(COL_FUNCTION),
            "go": {
                "biological_process": go_bp,
                "cellular_component": go_cc,
                "molecular_function": go_mf,
                "all": get(COL_GO_ALL),
                "ids": get(COL_GO_IDS),
            },
            "catalytic_activity": get(COL_CATALYTIC),
            "pathway": get(COL_PATHWAY),
            "source": {"database": "UniProtKB", "file": filename, "line": line_no},
        }

    # ---------------------------------------------------------------- lookup
    @staticmethod
    def _organism_matches(record, organism):
        """Organism context matches the numeric taxon ID exactly, or is a
        case-insensitive substring of the UniProt organism name (e.g.
        'SL1344' or 'Salmonella typhimurium')."""
        needle = organism.strip().lower()
        if not needle:
            return True
        if record["organism_id"] and record["organism_id"].strip() == organism.strip():
            return True
        return bool(record["organism"]) and needle in record["organism"].lower()

    def lookup(self, locus_tag, organism=None):
        self.ensure_loaded()
        query = (locus_tag or "").strip()
        base = {"locus_tag": locus_tag, "organism_context": organism or None}
        candidates = [self._records[i] for i in self._by_locus.get(query, [])]
        if organism and organism.strip():
            candidates = [r for r in candidates if self._organism_matches(r, organism)]

        if not candidates:
            return {**base, "status": STATUS_NOT_FOUND, "annotation": None,
                    "candidates": [],
                    "message": f"No UniProt annotation found for locus tag '{query}'"
                               + (f" in organism '{organism}'." if organism else ".")}
        if len(candidates) > 1:
            return {**base, "status": STATUS_AMBIGUOUS, "annotation": None,
                    "candidates": [self._public(r) for r in candidates],
                    "message": f"Locus tag '{query}' maps to {len(candidates)} UniProt "
                               "entries; no entry was selected automatically."}
        return {**base, "status": STATUS_MATCHED,
                "annotation": self._public(candidates[0]), "candidates": [],
                "message": None}

    @staticmethod
    def _public(record):
        return dict(record)

    def status(self):
        self.ensure_loaded()
        return {
            "directory_exists": os.path.isdir(self.directory),
            "files": self._sources,
            "errors": self._errors,
            "records": len(self._records),
            "indexed_locus_tags": len(self._by_locus),
        }


_service = None
_service_lock = threading.Lock()


def get_service():
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                _service = AnnotationService()
    return _service
