"""Shared helpers for the Micromix Phase-1 scalability benchmarks.

Responsibilities
----------------
* Safety: refuse to run against anything except the isolated benchmark mongod
  (127.0.0.1:BENCH_MONGO_PORT, default 27099) and verify an ownership marker
  before writing or dropping anything.
* Measurement: wall-clock timing, a background RSS sampler (peak RSS during an
  operation) and a hard memory guard that aborts the worker process.
* Results: append one JSON object per measurement to a JSONL file.
* Environment capture (OS, CPU, RAM, Python + library versions, MongoDB,
  Node, BLAS thread settings).

Nothing in here modifies Micromix application code. The backend directory is
only put on ``sys.path`` so its modules can be imported and called.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import platform
import subprocess
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
BACKEND = REPO / "Website" / "backend"
WORK = HERE / ".work"
DATA_DIR = WORK / "data"
RAW_DIR = WORK / "raw_results"
RESULTS_DIR = HERE / "results"

BENCH_MONGO_HOST = "127.0.0.1"
BENCH_MONGO_PORT = int(os.environ.get("BENCH_MONGO_PORT", "27099"))
BENCH_MONGO_URI = f"mongodb://{BENCH_MONGO_HOST}:{BENCH_MONGO_PORT}/"
FORBIDDEN_PORTS = {27017}

OWNERSHIP_DB = "bench_meta"
OWNERSHIP_COLL = "ownership"
OWNERSHIP_TAG = "micromix-scalability-phase1"
# Databases created by function-level benchmarks all carry this prefix and are
# registered in the ownership marker before first use.
BENCH_DB_PREFIX = "mmbench_"

# Conservative guards (overridable through the environment).
MEM_LIMIT_MB = int(os.environ.get("BENCH_MEM_LIMIT_MB", "6144"))
DEFAULT_TIMEOUT_S = int(os.environ.get("BENCH_TIMEOUT_S", "1800"))

SIZES = [32, 100, 250, 500, 1000]
N_FEATURES = 6000


# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------

class UnsafeEnvironment(RuntimeError):
    pass


def configure_backend_import():
    """Point the Micromix backend at the isolated mongod, then make it importable.

    MUST be called before ``import app`` (app.py connects at import time).
    """
    if BENCH_MONGO_PORT in FORBIDDEN_PORTS:
        raise UnsafeEnvironment(f"Port {BENCH_MONGO_PORT} is reserved for the developer DB.")
    existing = os.environ.get("MONGO_URI")
    if existing and existing != BENCH_MONGO_URI:
        raise UnsafeEnvironment(
            f"MONGO_URI is already set to {existing!r}; refusing to override silently. "
            "Unset it or set it to the benchmark URI."
        )
    os.environ["MONGO_URI"] = BENCH_MONGO_URI
    os.environ.pop("MONGODB_HOST", None)
    os.environ.pop("MONGODB_PORT", None)
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    # app.py resolves 'static/...' relative paths from the CWD.
    os.chdir(BACKEND)


def bench_client():
    from pymongo import MongoClient

    client = MongoClient(BENCH_MONGO_URI, serverSelectionTimeoutMS=3000)
    host, port = client.address  # forces server selection
    if port != BENCH_MONGO_PORT or host not in ("127.0.0.1", "localhost"):
        raise UnsafeEnvironment(f"Connected to unexpected server {host}:{port}")
    return client


def ensure_ownership(client):
    """Create (first run) or verify the ownership marker of the isolated instance.

    On first use the instance must be empty apart from MongoDB's own system
    databases, so that we never claim an instance that holds foreign data.
    """
    marker_coll = client[OWNERSHIP_DB][OWNERSHIP_COLL]
    marker = marker_coll.find_one({"_id": "owner"})
    names = set(client.list_database_names())
    if marker is None:
        foreign = names - {"admin", "config", "local", OWNERSHIP_DB, "micromix"}
        if foreign:
            raise UnsafeEnvironment(f"Instance holds unknown databases {sorted(foreign)}; refusing.")
        if "micromix" in names:
            # Only acceptable if it holds nothing except the indexes app.py
            # creates at import time (no documents).
            mm = client["micromix"]
            if any(mm[c].estimated_document_count() for c in mm.list_collection_names()):
                raise UnsafeEnvironment("'micromix' DB on benchmark instance holds data not created by us.")
        marker_coll.insert_one({
            "_id": "owner", "tag": OWNERSHIP_TAG, "created": _dt.datetime.utcnow(),
            "dbpath_hint": str(WORK / "mongo-data"), "owned_dbs": ["micromix"],
        })
        marker = marker_coll.find_one({"_id": "owner"})
    if marker.get("tag") != OWNERSHIP_TAG:
        raise UnsafeEnvironment("Ownership marker mismatch; refusing to use this instance.")
    return marker


def register_owned_db(client, name):
    if not name.startswith(BENCH_DB_PREFIX):
        raise UnsafeEnvironment(f"Benchmark DB names must start with {BENCH_DB_PREFIX!r}")
    client[OWNERSHIP_DB][OWNERSHIP_COLL].update_one(
        {"_id": "owner"}, {"$addToSet": {"owned_dbs": name}})


def drop_owned_db(client, name):
    marker = ensure_ownership(client)
    if name not in marker.get("owned_dbs", []) or not name.startswith(BENCH_DB_PREFIX):
        raise UnsafeEnvironment(f"Refusing to drop {name!r}: not registered as benchmark-owned.")
    client.drop_database(name)


# ---------------------------------------------------------------------------
# Measurement
# ---------------------------------------------------------------------------

def rss_mb():
    import psutil
    return psutil.Process().memory_info().rss / 1e6


class MemoryGuardExceeded(RuntimeError):
    pass


class RssSampler:
    """Samples RSS every ``interval`` seconds; enforces MEM_LIMIT_MB.

    If the limit is exceeded the guard writes a result line (via ``on_abort``)
    and terminates the process with exit code 3 -- the operation cannot be
    interrupted safely from another thread otherwise.
    """

    def __init__(self, interval=0.02, limit_mb=MEM_LIMIT_MB, on_abort=None):
        import psutil
        self._p = psutil.Process()
        self.interval = interval
        self.limit_mb = limit_mb
        self.on_abort = on_abort
        self.peak = 0.0
        self._stop = threading.Event()
        self._t = None

    def _run(self):
        while not self._stop.is_set():
            r = self._p.memory_info().rss / 1e6
            if r > self.peak:
                self.peak = r
            if r > self.limit_mb:
                if self.on_abort:
                    try:
                        self.on_abort(r)
                    finally:
                        os._exit(3)
                os._exit(3)
            time.sleep(self.interval)

    def __enter__(self):
        self.peak = self._p.memory_info().rss / 1e6
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._t.join()
        r = self._p.memory_info().rss / 1e6
        self.peak = max(self.peak, r)
        return False


class Recorder:
    """Appends measurement rows to a JSONL file."""

    def __init__(self, path: Path, run_id: str, workflow: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        self.workflow = workflow

    def write(self, **row):
        row.setdefault("run_id", self.run_id)
        row.setdefault("workflow", self.workflow)
        row.setdefault("timestamp", _dt.datetime.utcnow().isoformat() + "Z")
        with open(self.path, "a") as fh:
            fh.write(json.dumps(row, default=str) + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    @contextmanager
    def measure(self, operation, samples, rep, extra=None, cold=None):
        """Time one operation, sample RSS, record outcome (ok / error)."""
        extra = dict(extra or {})
        base = {"operation": operation, "samples": samples, "rep": rep, "cold": cold}

        def _abort(r):
            self.write(**base, status="memory_guard_exceeded",
                       error=f"RSS {r:.0f} MB > limit {MEM_LIMIT_MB} MB", **extra)

        before = rss_mb()
        box = {"extra": extra}
        w0 = time.time()
        t0 = time.perf_counter()
        status, err = "ok", None
        with RssSampler(on_abort=_abort) as s:
            try:
                yield box
            except Exception as exc:  # recorded, then re-raised to caller
                status, err = "error", f"{type(exc).__name__}: {exc}"[:2000]
                box["exception"] = exc
        elapsed = time.perf_counter() - t0
        wall = time.time() - w0
        # On macOS perf_counter (mach_absolute_time) stops during system
        # sleep while time.time() keeps going: a gap means the host slept and
        # the measurement is not trustworthy.
        status = box.get("status", status)
        if wall - elapsed > 2.0:
            status = "invalid_host_sleep"
            box["error"] = f"wall {wall:.1f}s vs monotonic {elapsed:.1f}s (host slept)"
        self.write(**base, status=status, error=box.get("error", err),
                   seconds=round(elapsed, 6), rss_before_mb=round(before, 1),
                   peak_rss_mb=round(s.peak, 1), peak_delta_mb=round(s.peak - before, 1),
                   **box["extra"])


# ---------------------------------------------------------------------------
# Environment capture
# ---------------------------------------------------------------------------

def _cmd(args):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=20).stdout.strip()
    except Exception as exc:  # noqa: BLE001
        return f"unavailable ({exc})"


def capture_environment(client=None):
    import numpy, pandas, pymongo, scipy, pyarrow
    env = {
        "captured_at": _dt.datetime.utcnow().isoformat() + "Z",
        "os": f"{platform.system()} {platform.release()} ({_cmd(['sw_vers', '-productVersion'])})",
        "machine": platform.machine(),
        "cpu": _cmd(["sysctl", "-n", "machdep.cpu.brand_string"]),
        "cpu_count": os.cpu_count(),
        "ram_bytes": int(_cmd(["sysctl", "-n", "hw.memsize"]) or 0),
        "python": sys.version.split()[0],
        "python_executable": sys.executable,
        "numpy": numpy.__version__, "pandas": pandas.__version__,
        "pymongo": pymongo.version, "scipy": scipy.__version__, "pyarrow": pyarrow.__version__,
        "node": _cmd(["node", "--version"]),
        "mongod_binary": _cmd(["mongod", "--version"]).splitlines()[0] if _cmd(["mongod", "--version"]) else None,
        "blas_env": {k: os.environ.get(k) for k in (
            "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
            "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS")},
        "mem_limit_mb": MEM_LIMIT_MB,
        "git_head": _cmd(["git", "-C", str(REPO), "rev-parse", "HEAD"]),
        "git_branch": _cmd(["git", "-C", str(REPO), "branch", "--show-current"]),
    }
    try:
        import threadpoolctl
        env["threadpools"] = threadpoolctl.threadpool_info()
    except Exception:  # noqa: BLE001
        env["threadpools"] = "threadpoolctl unavailable"
    try:
        cfg = numpy.show_config(mode="dicts")  # numpy >= 1.25
        env["numpy_blas"] = cfg.get("Build Dependencies", {}).get("blas")
    except Exception:  # noqa: BLE001
        pass
    if client is not None:
        env["mongodb_server"] = client.server_info().get("version")
        env["mongodb_uri"] = BENCH_MONGO_URI
    return env


def new_run_id():
    return _dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]


def coll_stats(db, name):
    try:
        s = db.command("collStats", name)
        return {"count": s.get("count"), "size_bytes": s.get("size"),
                "storage_bytes": s.get("storageSize"), "index_bytes": s.get("totalIndexSize"),
                "avg_obj_bytes": s.get("avgObjSize"), "n_indexes": s.get("nindexes")}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
