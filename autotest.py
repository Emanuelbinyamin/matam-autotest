#!/usr/bin/env python3
"""
autotest — Matam Auto-Test  (Technion 234124)
Strict-compilation, I/O diffing, Valgrind, and Git workflow in one command.
"""

import argparse
import difflib
import glob
import os
import re
import subprocess
import sys
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple


# ─────────────────────────────────────────────────────────────── Palette ──

class _C:
    RESET   = "\033[0m"
    BOLD    = "\033[1m"
    DIM     = "\033[2m"
    RED     = "\033[91m"
    GREEN   = "\033[92m"
    YELLOW  = "\033[93m"
    CYAN    = "\033[96m"
    MAGENTA = "\033[95m"
    BLUE    = "\033[94m"
    WHITE   = "\033[97m"


def _col(text: str, *codes: str) -> str:
    return "".join(codes) + text + _C.RESET

def c_ok(t: str)     -> str: return _col(t, _C.BOLD, _C.GREEN)
def c_fail(t: str)   -> str: return _col(t, _C.BOLD, _C.RED)
def c_warn(t: str)   -> str: return _col(t, _C.BOLD, _C.YELLOW)
def c_info(t: str)   -> str: return _col(t, _C.BOLD, _C.CYAN)
def c_header(t: str) -> str: return _col(t, _C.BOLD, _C.MAGENTA)
def c_git(t: str)    -> str: return _col(t, _C.BOLD, _C.BLUE)
def c_dim(t: str)    -> str: return _col(t, _C.DIM)
def c_bold(t: str)   -> str: return _col(t, _C.BOLD, _C.WHITE)


# ──────────────────────────────────────────────────────────── Constants ──

DEFAULT_TESTS_DIR          = "tests"
DEFAULT_TIMEOUT_SECS       = 5.0
VALGRIND_TIMEOUT_MULTIPLIER = 15
CPP_COMPILE_FLAGS          = ["-std=c++17", "-Wall", "-pedantic-errors", "-Werror", "-g"]
PACK_PATTERNS              = ("*.cpp", "*.h", "*.pdf", "Makefile", "makefile")


# ───────────────────────────────────────────────────────── Data models ──

@dataclass
class TestCase:
    name: str
    input_path: Path
    expected_path: Path


@dataclass
class TestResult:
    test: TestCase
    passed: bool
    actual_output: str   = ""
    expected_output: str = ""
    unified_diff: str    = ""
    error_message: str   = ""
    timed_out: bool      = False
    runtime_secs: float  = 0.0
    mem_ok: Optional[bool] = None
    valgrind_log: str    = ""


@dataclass
class GitResult:
    attempted: bool  = False
    add_ok: bool     = False
    commit_ok: bool  = False
    push_ok: bool    = False
    commit_msg: str  = ""
    push_out: str    = ""
    error: str       = ""


# ───────────────────────────────────────────────────── Test discovery ──

def discover_tests(tests_dir: str) -> List[TestCase]:
    root = Path(tests_dir)
    if not root.is_dir():
        return []

    files = {f.name for f in root.iterdir()}

    def extract_index(filename: str, suffix: str) -> Optional[int]:
        m = re.match(rf"^test(\d+)\.{suffix}$", filename)
        return int(m.group(1)) if m else None

    inputs   = {extract_index(f, "in"):       f for f in files if extract_index(f, "in")       is not None}
    expected = {extract_index(f, "expected"): f for f in files if extract_index(f, "expected") is not None}

    return [
        TestCase(
            name=f"test{n}",
            input_path=root / inputs[n],
            expected_path=root / expected[n],
        )
        for n in sorted(inputs.keys() & expected.keys())
    ]


# ──────────────────────────────────────────────────────── Compilation ──

def _infer_makefile_binary(source_stem: str) -> str:
    """
    Parse the Makefile for a common target-variable declaration
    (EXEC, TARGET, BIN, or PROG).  Falls back to the source file stem.

    Handles both '= value' and ':= value' assignment forms.
    """
    var_pattern = re.compile(
        r"^(?:EXEC|TARGET|BIN|PROG)\s*(?::?=)\s*(\S+)", re.IGNORECASE
    )
    for makefile_name in ("Makefile", "makefile"):
        path = Path(makefile_name)
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            m = var_pattern.match(line)
            if m:
                return f"./{m.group(1)}"
    return f"./{source_stem}"


def compile_cpp(source_path: str, tmp_binary: str) -> Tuple[bool, str, str]:
    """
    Compile source_path.  Returns (success, compiler_output, resolved_binary_path).

    Uses Makefile when present; falls back to a direct g++ invocation.
    The returned binary path is verified to exist by the caller.
    """
    has_makefile = Path("Makefile").exists() or Path("makefile").exists()

    if has_makefile:
        print(c_info("   → Makefile detected — running 'make'..."))
        try:
            res = subprocess.run(
                ["make"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            binary = _infer_makefile_binary(Path(source_path).stem)
            return res.returncode == 0, res.stdout, binary
        except FileNotFoundError:
            return False, "'make' not found in PATH.", ""

    try:
        res = subprocess.run(
            ["g++"] + CPP_COMPILE_FLAGS + [source_path, "-o", tmp_binary],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        return res.returncode == 0, res.stdout, tmp_binary
    except FileNotFoundError:
        return False, "'g++' not found in PATH.", ""


# ───────────────────────────────────────────────── Program execution ──

def run_program(
    cmd: List[str], in_path: Path, timeout: float
) -> Tuple[bool, str, str, bool, float]:
    """
    Execute cmd with in_path fed to stdin.
    Returns (exit_ok, stdout, stderr, timed_out, elapsed_secs).
    """
    try:
        with in_path.open("r", encoding="utf-8") as fh:
            t0 = time.monotonic()
            proc = subprocess.run(
                cmd,
                stdin=fh,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout,
            )
            return (
                proc.returncode == 0,
                proc.stdout,
                proc.stderr,
                False,
                time.monotonic() - t0,
            )
    except subprocess.TimeoutExpired:
        return False, "", "", True, timeout


def run_valgrind(binary: str, in_path: Path, timeout: float) -> Tuple[bool, str]:
    """
    Run Valgrind over binary with in_path on stdin.
    Returns (no_memory_errors, valgrind_stderr).
    """
    try:
        with in_path.open("r", encoding="utf-8") as fh:
            res = subprocess.run(
                [
                    "valgrind",
                    "--leak-check=full",
                    "--show-leak-kinds=all",
                    "--track-origins=yes",
                    "--error-exitcode=1",
                    binary,
                ],
                stdin=fh,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout * VALGRIND_TIMEOUT_MULTIPLIER,
            )
        return res.returncode == 0, res.stderr
    except subprocess.TimeoutExpired:
        return False, "Valgrind timed out."
    except FileNotFoundError:
        return False, "valgrind not found in PATH."


# ─────────────────────────────────────────────────── Output renderers ──

def _render_diff(diff: str) -> None:
    print(c_info("   ── diff  (─ expected  /  + actual) ──"))
    for line in diff.splitlines():
        if   line.startswith("+") and not line.startswith("+++"):
            print(c_ok(f"   {line}"))
        elif line.startswith("-") and not line.startswith("---"):
            print(c_fail(f"   {line}"))
        else:
            print(c_dim(f"   {line}"))


def _render_valgrind(log: str) -> None:
    print(c_fail("   ── Valgrind report ──"))
    strip_pid = re.compile(r"^==\d+==\s*")
    loc_pat   = re.compile(r"([a-zA-Z0-9_\-]+\.[cph]+:\d+)")
    for line in log.strip().splitlines():
        clean = strip_pid.sub("", line)
        if any(k in clean.lower() for k in ("lost:", "uninit", "invalid", "error summary:")):
            print(c_fail(f"   ✗ {clean}"))
        elif m := loc_pat.search(clean):
            print(c_warn(f"     → {m.group(1)}"))


def print_summary(results: List[TestResult]) -> None:
    total     = len(results)
    n_passed  = sum(1 for r in results if r.passed)
    n_memleak = sum(1 for r in results if r.mem_ok is False)
    n_timeout = sum(1 for r in results if r.timed_out)

    bar_width = 40
    filled    = round(bar_width * n_passed / total) if total else 0
    bar       = c_ok("█" * filled) + c_fail("░" * (bar_width - filled))

    print()
    print(c_header("  ── Summary " + "─" * 52))
    print(f"  {bar}  {c_bold(str(n_passed))}/{c_bold(str(total))} passed")
    if n_memleak:
        print(c_fail(f"  ⚠  {n_memleak} test(s) with memory errors"))
    if n_timeout:
        print(c_warn(f"  ⚠  {n_timeout} test(s) timed out"))
    print()


# ───────────────────────────────────────────────────────── Test runner ──

def _run_single_test(
    tc: TestCase,
    cmd: List[str],
    timeout: float,
    use_valgrind: bool,
    bin_path: Optional[str],
) -> TestResult:
    """Pure computation: run one test, return its result. No I/O side effects."""
    expected_text = tc.expected_path.read_text(encoding="utf-8")
    ok, out, err, timed_out, elapsed = run_program(cmd, tc.input_path, timeout)

    if timed_out:
        return TestResult(tc, passed=False, timed_out=True)

    actual_lines   = [l.rstrip() for l in out.splitlines()]
    expected_lines = [l.rstrip() for l in expected_text.splitlines()]
    passed = actual_lines == expected_lines
    diff = "\n".join(
        difflib.unified_diff(
            expected_lines, actual_lines,
            fromfile="expected", tofile="actual",
            lineterm="", n=3,
        )
    )
    result = TestResult(tc, passed, out, expected_text, diff, err, runtime_secs=elapsed)

    if use_valgrind and bin_path and passed:
        result.mem_ok, result.valgrind_log = run_valgrind(bin_path, tc.input_path, timeout)

    return result


def execute_tests(
    cmd: List[str],
    tests: List[TestCase],
    timeout: float,
    use_valgrind: bool,
    bin_path: Optional[str],
) -> List[TestResult]:
    """Orchestrate test execution and stream per-test output to stdout."""
    results: List[TestResult] = []

    for idx, tc in enumerate(tests, 1):
        result = _run_single_test(tc, cmd, timeout, use_valgrind, bin_path)
        label  = f"[{idx}/{len(tests)}] {c_bold(tc.name)}"

        if result.timed_out:
            print(f"  {c_fail('✗ TIMEOUT')} {label}")
        else:
            mem_tag = (
                f"  {c_ok('✓ memcheck')}"  if result.mem_ok is True  else
                f"  {c_fail('✗ memleak')}" if result.mem_ok is False else
                ""
            )
            status = c_ok("✓ PASS") if result.passed else c_fail("✗ FAIL")
            print(f"  {status} {label}  {result.runtime_secs * 1000:.1f}ms{mem_tag}")

            if not result.passed:
                _render_diff(result.unified_diff)
            elif result.mem_ok is False:
                _render_valgrind(result.valgrind_log)

        results.append(result)

    return results


# ──────────────────────────────────────────────────────── Git workflow ──

def run_git_workflow(message: str) -> GitResult:
    gr = GitResult(attempted=True, commit_msg=message)

    # --git-dir exits non-zero if not inside a repository.
    if subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode != 0:
        gr.error = "Not a Git repository."
        return gr

    gr.add_ok = (
        subprocess.run(["git", "add", "."], capture_output=True).returncode == 0
    )

    r_commit = subprocess.run(
        ["git", "commit", "-m", f"[Autotest] {message}"],
        capture_output=True,
        text=True,
    )
    gr.commit_ok = (
        r_commit.returncode == 0
        or "nothing to commit" in r_commit.stdout.lower()
    )

    if gr.commit_ok:
        r_push      = subprocess.run(["git", "push"], capture_output=True, text=True)
        gr.push_ok  = r_push.returncode == 0
        gr.push_out = r_push.stderr or r_push.stdout

    return gr


def print_git_result(gr: GitResult) -> None:
    print(c_git("\n  GIT WORKFLOW\n  " + "─" * 62))
    print(f"  {'✓' if gr.add_ok else '✗'} git add .")
    if gr.commit_ok:
        print(f"  ✓ git commit -m \"[Autotest] {gr.commit_msg}\"")
    if gr.push_ok:
        print(f"  ✓ git push")
    if gr.error:
        print(c_fail(f"  ✗ {gr.error}"))


# ─────────────────────────────────────────────────────── Moodle packer ──

def pack_submission(student_id: str, any_failure: bool) -> None:
    print(c_info("\n  MOODLE PACKAGER\n  " + "─" * 62))
    if any_failure:
        print(c_fail("  ✗ Tests failed — packing aborted to prevent a bad submission."))
        return

    zname = f"{student_id}.zip"
    with zipfile.ZipFile(zname, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for pattern in PACK_PATTERNS:
            for fpath in glob.glob(pattern):
                zf.write(fpath)
                print(c_dim(f"   → {fpath}"))
    print(c_ok(f"  ✓ Created: {zname}"))


# ───────────────────────────────────────────── Argument parser ──

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="autotest",
        description="Matam auto-tester: compile, I/O diff, Valgrind, Git.",
    )
    p.add_argument(
        "source",
        help="Path to a .cpp source file or a .py script.",
    )
    p.add_argument(
        "--save",
        metavar="MSG",
        help="Git add + commit + push with this message after the test run.",
    )
    p.add_argument(
        "--pack",
        metavar="ID",
        help="Create a Moodle-ready <ID>.zip — only if all tests pass.",
    )
    p.add_argument(
        "--tests-dir",
        metavar="DIR",
        default=DEFAULT_TESTS_DIR,
        help=f"Directory containing test cases (default: '{DEFAULT_TESTS_DIR}').",
    )
    p.add_argument(
        "--timeout",
        metavar="SEC",
        type=float,
        default=DEFAULT_TIMEOUT_SECS,
        help=f"Per-test timeout in seconds (default: {DEFAULT_TIMEOUT_SECS}).",
    )
    p.add_argument(
        "--no-valgrind",
        action="store_true",
        help="Skip Valgrind memory checks.",
    )
    return p


# ──────────────────────────────────────────────────────── Entry point ──

def main() -> None:
    args   = build_parser().parse_args()
    source = Path(args.source)

    print(c_header(
        f"\n╔══ autotest v3 ════════════════════════════════════════════════╗\n"
        f"║  Target : {str(source):<54}║\n"
        f"╚═══════════════════════════════════════════════════════════════╝\n"
    ))

    is_cpp    = source.suffix == ".cpp"
    is_python = source.suffix == ".py"

    if not is_cpp and not is_python:
        print(c_fail(f"✗ Unsupported source type '{source.suffix}'. Use .cpp or .py."))
        sys.exit(1)

    # ── Secure temporary binary (guaranteed cleanup via finally) ──────
    tmp_fd, tmp_binary = tempfile.mkstemp(prefix="autotest_")
    os.close(tmp_fd)

    try:
        # ── Compilation ───────────────────────────────────────────────
        bin_path: Optional[str] = None
        cmd: List[str]

        if is_cpp:
            print(c_info("Compiling…"))
            ok, output, bin_path = compile_cpp(str(source), tmp_binary)

            if not ok:
                print(c_fail("✗ Compilation failed\n"))
                for line in output.strip().splitlines():
                    print(c_fail(f"   {line}"))
                sys.exit(1)

            if not Path(bin_path).exists():
                print(c_fail(
                    f"✗ Binary not found at '{bin_path}' after compilation.\n"
                    f"   Check that your Makefile target name matches the EXEC variable."
                ))
                sys.exit(1)

            print(c_ok("✓ Compilation successful\n"))
            cmd = [bin_path]

        else:  # .py
            cmd = [sys.executable, str(source)]

        # ── Test discovery ────────────────────────────────────────────
        tests = discover_tests(args.tests_dir)
        if not tests:
            print(c_warn(f"No test cases found in '{args.tests_dir}/'."))
            sys.exit(0)

        # ── Valgrind availability ─────────────────────────────────────
        use_valgrind = (
            is_cpp
            and not args.no_valgrind
            and subprocess.run(
                ["which", "valgrind"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ).returncode == 0
        )

        # ── Run tests ─────────────────────────────────────────────────
        results     = execute_tests(cmd, tests, args.timeout, use_valgrind, bin_path)
        any_failure = any(not r.passed or r.mem_ok is False for r in results)
        print_summary(results)

        # ── Git ───────────────────────────────────────────────────────
        if args.save:
            print_git_result(run_git_workflow(args.save))

        # ── Pack ──────────────────────────────────────────────────────
        if args.pack:
            pack_submission(args.pack, any_failure)

        sys.exit(1 if any_failure else 0)

    finally:
        # Unconditional cleanup: runs even on sys.exit(), exceptions, or Ctrl-C.
        if Path(tmp_binary).exists():
            os.unlink(tmp_binary)


if __name__ == "__main__":
    main()