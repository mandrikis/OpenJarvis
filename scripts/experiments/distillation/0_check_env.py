#!/usr/bin/env python3
"""Step 0: Validate the distillation pipeline environment.

Prints every path and env var the pipeline cares about, whether each
exists, and exits non-zero if anything critical is still missing after
two best-effort fixups:

  * If env vars (e.g. ANTHROPIC_API_KEY) are unset, source <repo>/.env.
  * If ~/.openjarvis/learning/ is missing, run `jarvis learning init`.

    python 0_check_env.py
"""

from __future__ import annotations


# distill-streaming-fix
import logging as _logging
import sys as _sys
try:
    _sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
    _sys.stderr.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
except AttributeError:
    pass
_logging.basicConfig(
    level=_logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=_sys.stdout,
    force=True,
)

import os
import shutil
import subprocess
import sys
from pathlib import Path

try:
    import tomllib  # type: ignore[import-not-found]
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[import-not-found,no-redef]

HERE = Path(__file__).resolve().parent
REPO_ROOT = Path(__file__).resolve().parents[3]
MATRIX = HERE / "pipeline_matrix.toml"


def color(code: str, s: str) -> str:
    return f"\033[{code}m{s}\033[0m" if sys.stdout.isatty() else s


OK = color("0;32", "[ OK ]")
WARN = color("1;33", "[WARN]")
FAIL = color("0;31", "[FAIL]")
INFO = color("0;34", "[INFO]")


def section(title: str) -> None:
    print()
    print(title)
    print("-" * 72)


def load_dotenv_if_unset(env_path: Path) -> list[str]:
    """Populate os.environ from a shell-style .env, only for keys not already set."""
    if not env_path.exists():
        return []
    loaded: list[str] = []
    for raw in env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
            loaded.append(key)
    return loaded


def try_jarvis_learning_init() -> tuple[bool, str]:
    jarvis = Path(sys.executable).parent / "jarvis"
    if not jarvis.exists():
        found = shutil.which("jarvis")
        if not found:
            return False, "jarvis CLI not found in venv or PATH"
        jarvis = Path(found)
    try:
        result = subprocess.run(
            [str(jarvis), "learning", "init"],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except Exception as e:
        return False, f"failed to invoke jarvis: {e}"
    msg = (result.stdout or result.stderr).strip()
    return result.returncode == 0, msg


def main() -> int:
    if not MATRIX.exists():
        print(f"{FAIL} matrix not found at {MATRIX}", file=sys.stderr)
        return 1

    matrix = tomllib.loads(MATRIX.read_text())
    paths = matrix.get("paths", {})
    runner = matrix.get("runner", {})
    apps = matrix.get("applications", [])

    print("=" * 72)
    print("  Distillation pipeline environment check")
    print("=" * 72)
    print(f"  matrix    : {MATRIX}")
    print(f"  repo root : {REPO_ROOT}")

    critical_failures = 0

    # ── Required env vars ──────────────────────────────────────────────────
    section("Environment variables")
    dotenv_path = REPO_ROOT / ".env"
    loaded_keys = load_dotenv_if_unset(dotenv_path)
    if loaded_keys:
        print(f"  {INFO} sourced {len(loaded_keys)} key(s) from {dotenv_path}: "
              f"{', '.join(loaded_keys)}")
    if os.environ.get("ANTHROPIC_API_KEY"):
        n = len(os.environ["ANTHROPIC_API_KEY"])
        print(f"  {OK} ANTHROPIC_API_KEY   set (len={n}) — used by step 2 judge")
    else:
        print(f"  {FAIL} ANTHROPIC_API_KEY   not set — step 2 will fail")
        critical_failures += 1

    home_override = os.environ.get("OPENJARVIS_HOME")
    if home_override:
        p = Path(home_override)
        marker = OK if p.exists() else WARN
        print(f"  {marker} OPENJARVIS_HOME     {p}  (forces step 2 single-db mode)")
    else:
        print(
            f"  {INFO} OPENJARVIS_HOME     unset — step 2 walks per-cell dbs "
            f"under matrix results dirs"
        )

    # ── Matrix [paths] ─────────────────────────────────────────────────────
    section("Matrix [paths]  (relative to repo root)")
    path_descriptions = [
        ("configs_dir", "step 1 reads baseline TOMLs from"),
        ("distilled_configs_dir", "step 5 writes / step 6 reads distilled TOMLs"),
        ("baseline_results_dir", "step 1 writes summary.json + traces.db"),
        ("distilled_results_dir", "step 6 writes summary.json + traces.db"),
        ("comparison_dir", "step 7 writes comparison.json"),
    ]
    for key, purpose in path_descriptions:
        rel = paths.get(key, "")
        if not rel:
            print(f"  {WARN} {key:24} (unset)")
            continue
        full = (REPO_ROOT / rel).resolve()
        kind = "exists" if full.exists() else "will be created"
        marker = OK if full.exists() else INFO
        print(f"  {marker} {key:24} {full}  ({kind})")
        print(f"           ↳ {purpose}")

    # ── Matrix [runner] ────────────────────────────────────────────────────
    section("Matrix [runner]")
    oj_dir = (runner.get("oj_config_dir") or "").strip()
    if oj_dir:
        full = Path(oj_dir)
        marker = OK if full.exists() else WARN
        kind = (
            "exists"
            if full.exists()
            else "missing — runner will warn and skip override"
        )
        print(f"  {marker} oj_config_dir       {full}  ({kind})")
    else:
        print(f"  {INFO} oj_config_dir       (empty — no OPENJARVIS_CONFIG override)")

    py = runner.get("python_bin", ".venv/bin/python")
    py_path = Path(py) if Path(py).is_absolute() else (REPO_ROOT / py)
    if py_path.exists():
        print(f"  {OK} python_bin          {py_path}")
    else:
        sys_py = shutil.which("python") or sys.executable
        print(
            f"  {WARN} python_bin          {py_path}  (missing — runner will fall "
            f"back to {sys_py})"
        )

    print(
        f"  {INFO} evals_module        {runner.get('evals_module', 'openjarvis.evals')}"
    )

    # ── Learning artifacts (step 3 prereq) ─────────────────────────────────
    section("Learning artifacts  (`jarvis learning init` writes these)")
    learn_root = Path.home() / ".openjarvis" / "learning"
    if learn_root.exists():
        sessions_dir = learn_root / "sessions"
        sessions = list(sessions_dir.glob("*")) if sessions_dir.exists() else []
        plans = list(sessions_dir.glob("*/plan.json")) if sessions_dir.exists() else []
        print(f"  {OK} {learn_root}")
        print(
            f"           ↳ {len(sessions)} session(s), {len(plans)} plan.json file(s)"
        )
    else:
        print(f"  {WARN} {learn_root} missing — running: jarvis learning init")
        ok, msg = try_jarvis_learning_init()
        if msg:
            for line in msg.splitlines():
                print(f"           ↳ {line}")
        if ok and learn_root.exists():
            print(f"  {OK} {learn_root}  (created)")
        else:
            print(f"  {FAIL} init did not create {learn_root}")
            critical_failures += 1

    # ── Discovered traces.db files ─────────────────────────────────────────
    section("Per-cell traces.db files  (what step 2 will judge by default)")
    found: list[Path] = []
    for key in ("baseline_results_dir", "distilled_results_dir"):
        rel = paths.get(key, "")
        if not rel:
            continue
        root = (REPO_ROOT / rel).resolve()
        if root.exists():
            found.extend(sorted(root.rglob("traces.db")))
    if found:
        for p in found:
            try:
                rel_p = p.relative_to(REPO_ROOT)
            except ValueError:
                rel_p = p
            size_kb = p.stat().st_size / 1024
            print(f"  {OK} {rel_p}  ({size_kb:.0f} KB)")
    else:
        fb = Path.home() / ".openjarvis" / "traces.db"
        print(f"  {INFO} no per-cell traces.db yet — step 2 will fall back to {fb}")

    # ── vLLM hosts (best-effort) ───────────────────────────────────────────
    if apps:
        section("vLLM hosts declared in matrix [[applications]]  (not probed here)")
        for app in apps:
            print(
                f"  {INFO} {app.get('size', '?'):>3}  slug={app.get('slug', '?'):14} "
                f"port={app.get('vllm_port', '?')}  hf={app.get('hf_name', '?')}"
            )
        print(
            f"  {INFO} Step 1 / step 6 health-probe each port at run time; "
            f"see _eval_runner.py:check_vllm"
        )

    # ── Summary ────────────────────────────────────────────────────────────
    print()
    if critical_failures:
        print(
            f"{FAIL} {critical_failures} critical problem(s); fix before running step 1."
        )
        return 1
    print(f"{OK} environment looks good. Safe to run step 1.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
