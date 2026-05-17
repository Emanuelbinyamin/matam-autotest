#!/usr/bin/env python3
"""
autotest v2 — Automated I/O, memory, and Git workflow utility.
Technion CS 234124-compliant C++17 compilation flags.

Usage:
    autotest main.cpp [options]
    autotest solution.py [options]
    autotest main.cpp --save "Implement part 3"
"""

import argparse
import difflib
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

# ══════════════════════════════════════════════════════════════════════════════
# § 1 · ANSI COLOR LAYER
# ══════════════════════════════════════════════════════════════════════════════

class _C:
    RESET   = "\033[0m"
    BOLD    = "\033[1m"
    DIM     = "\033[2m"
    RED     = "\033[91m"
    GREEN   = "\033[92m"
    YELLOW  = "\033[93m"
    CYAN    = "\033[96m"
    MAGENTA = "\033[95m"
    WHITE   = "\033[97m"
    BLUE    = "\033[94m"


# Module-level toggle; set to False by --no-color or a non-tty stdout.
_COLOR_ENABLED: bool = True


def _tty_ok() -> bool:
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def colorize(text: str, *codes: str) -> str:
    if not _COLOR_ENABLED or not _tty_ok():
        return text
    return "".join(codes) + text + _C.RESET


# Semantic wrappers — always use these; never raw codes outside this section.
def c_ok(t: str)     -> str: return colorize(t, _C.BOLD, _C.GREEN)
def c_fail(t: str)   -> str: return colorize(t, _C.BOLD, _C.RED)
def c_warn(t: str)   -> str: return colorize(t, _C.BOLD, _C.YELLOW)
def c_info(t: str)   -> str: return colorize(t, _C.BOLD, _C.CYAN)
def c_header(t: str) -> str: return colorize(t, _C.BOLD, _C.MAGENTA)
def c_git(t: str)    -> str: return colorize(t, _C.BOLD, _C.BLUE)
def c_dim(t: str)    -> str: return colorize(t, _C.DIM)
def c_bold(t: str)   -> str: return colorize(t, _C.BOLD, _C.WHITE)


# ══════════════════════════════════════════════════════════════════════════════
# § 2 · DATA STRUCTURES
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class TestCase:
    """A paired (input, expected-output) test case."""
    name:          str
    input_path:    str
    expected_path: str


@dataclass
class TestResult:
    """All data produced by executing one TestCase."""
    test:            TestCase
    passed:          bool
    actual_output:   str   = ""
    expected_output: str   = ""
    unified_diff:    str   = ""   # Pre-computed; avoids calling compare twice
    error_message:   str   = ""   # Runtime stderr or exception text
    timed_out:       bool  = False
    runtime_secs:    float = 0.0
    # Valgrind fields: None = not run
    mem_ok:          Optional[bool] = None
    valgrind_log:    str            = ""


@dataclass
class GitResult:
    """Outcome of the optional --save Git workflow."""
    attempted:  bool = False
    add_ok:     bool = False
    commit_ok:  bool = False
    push_ok:    bool = False
    commit_msg: str  = ""
    add_out:    str  = ""
    commit_out: str  = ""
    push_out:   str  = ""
    error:      str  = ""   # Pre-step fatal error (no git, not a repo, etc.)


# ══════════════════════════════════════════════════════════════════════════════
# § 3 · TEST DISCOVERY
# ══════════════════════════════════════════════════════════════════════════════

# Compiled at module load; used for Scheme A numeric sort.
_A_IN_RE  = re.compile(r"^test(\d+)\.in$")
_A_EXP_RE = re.compile(r"^test(\d+)\.expected$")


def discover_tests(tests_dir: str) -> List[TestCase]:
    """
    Scans *tests_dir* for input / expected-output file pairs.

    Three naming schemes are supported, checked in priority order.
    A name matched by a higher-priority scheme is excluded from lower ones.

      Scheme A — Technion 234124 canonical (numerically sorted):
        test1.in  /  test1.expected
        test12.in /  test12.expected

      Scheme B — same stem, .in / .out (lexicographically sorted):
        test1.in  /  test1.out
        sample.in /  sample.out

      Scheme C — in_/out_ prefix with .txt extension:
        in_1.txt  /  out_1.txt
        in_hard.txt / out_hard.txt

    All three schemes may coexist; de-duplication is by canonical display name.
    """
    if not os.path.isdir(tests_dir):
        return []

    all_files  = set(os.listdir(tests_dir))
    tests: List[TestCase] = []
    seen:  set            = set()

    # ── Scheme A: test<N>.in / test<N>.expected ───────────────────────────
    a_in  = {int(m.group(1)): f for f in all_files if (m := _A_IN_RE.match(f))}
    a_exp = {int(m.group(1)): f for f in all_files if (m := _A_EXP_RE.match(f))}

    for num in sorted(set(a_in) & set(a_exp)):          # numeric order
        name = f"test{num}"
        tests.append(TestCase(
            name=name,
            input_path=os.path.join(tests_dir, a_in[num]),
            expected_path=os.path.join(tests_dir, a_exp[num]),
        ))
        seen.add(name)

    # ── Scheme B: *.in / *.out — same stem ───────────────────────────────
    b_in  = {os.path.splitext(f)[0]: f for f in all_files if f.endswith(".in")}
    b_out = {os.path.splitext(f)[0]: f for f in all_files if f.endswith(".out")}

    for stem in sorted(set(b_in) & set(b_out)):
        if stem in seen:
            continue
        tests.append(TestCase(
            name=stem,
            input_path=os.path.join(tests_dir, b_in[stem]),
            expected_path=os.path.join(tests_dir, b_out[stem]),
        ))
        seen.add(stem)

    # ── Scheme C: in_<key>.txt / out_<key>.txt ────────────────────────────
    c_in  = {f[3:-4]: f for f in all_files if f.startswith("in_")  and f.endswith(".txt")}
    c_out = {f[4:-4]: f for f in all_files if f.startswith("out_") and f.endswith(".txt")}

    for key in sorted(set(c_in) & set(c_out)):
        canonical = f"in_{key}"
        if canonical in seen:
            continue
        tests.append(TestCase(
            name=canonical,
            input_path=os.path.join(tests_dir, c_in[key]),
            expected_path=os.path.join(tests_dir, c_out[key]),
        ))
        seen.add(canonical)

    return tests


# ══════════════════════════════════════════════════════════════════════════════
# § 4 · C++ COMPILATION  (Technion 234124 — C++17)
# ══════════════════════════════════════════════════════════════════════════════

# Exact flags mandated by Technion course 234124.
#   -std=c++17        : C++17 standard.
#   -Wall             : Full standard warning set.
#   -pedantic-errors  : ISO C++ violations are hard errors (not warnings).
#   -Werror           : All remaining warnings promoted to errors.
# NOTE: -Wextra is intentionally absent per the course spec.
_CPP_FLAGS   = ["g++", "-std=c++17", "-Wall", "-pedantic-errors", "-Werror", "-g"]
_BINARY_PATH = "/tmp/autotest_binary"   # /tmp avoids cwd permission issues


def compile_cpp(source_path: str) -> Tuple[bool, str]:
    """
    Compiles *source_path* with the Technion 234124 flags.
    Returns (success, merged_compiler_output).

    stderr is merged into stdout: g++ emits diagnostics on either stream
    depending on the internal error category.
    """
    cmd = _CPP_FLAGS + [source_path, "-o", _BINARY_PATH]
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,   # merge
            text=True,
        )
    except FileNotFoundError:
        return (False, "g++ not found. Install: sudo apt install g++")
    return (result.returncode == 0, result.stdout)


def cleanup_binary() -> None:
    if os.path.exists(_BINARY_PATH):
        try:
            os.remove(_BINARY_PATH)
        except OSError:
            pass


# ══════════════════════════════════════════════════════════════════════════════
# § 5 · PROGRAM RUNNER
# ══════════════════════════════════════════════════════════════════════════════

def run_program(
    cmd: List[str],
    input_path: str,
    timeout: float,
) -> Tuple[bool, str, str, bool, float]:
    """
    Executes *cmd* with stdin from *input_path* and a wall-clock timeout.

    Returns:
        (exit_ok, stdout, stderr, timed_out, elapsed_seconds)

    Output correctness (I/O match) is the canonical pass criterion.
    A non-zero exit code is reported as error_message but does not itself
    constitute a failure — the caller decides based on output comparison.
    """
    try:
        with open(input_path, "r", encoding="utf-8", errors="replace") as fh:
            t0 = time.monotonic()
            proc = subprocess.run(
                cmd,
                stdin=fh,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout,
            )
            elapsed = time.monotonic() - t0
        return (proc.returncode == 0, proc.stdout, proc.stderr, False, elapsed)

    except subprocess.TimeoutExpired:
        return (False, "", "", True, timeout)
    except FileNotFoundError as exc:
        return (False, "", f"Executable not found: {exc}", False, 0.0)
    except OSError as exc:
        return (False, "", f"OS error: {exc}", False, 0.0)


# ══════════════════════════════════════════════════════════════════════════════
# § 6 · VALGRIND MEMORY CHECKER
# ══════════════════════════════════════════════════════════════════════════════

_VALGRIND_FLAGS = [
    "valgrind",
    "--leak-check=full",
    "--show-leak-kinds=all",
    "--track-origins=yes",
    "--error-exitcode=1",
]
_VG_TIMEOUT_FACTOR = 15   # Valgrind is typically 10-20× slower than native


def valgrind_available() -> bool:
    r = subprocess.run(["which", "valgrind"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return r.returncode == 0


def run_valgrind(
    binary: str,
    input_path: str,
    base_timeout: float,
) -> Tuple[bool, str]:
    """
    Runs *binary* under Valgrind with the same stdin as the I/O test.
    Returns (memory_clean, valgrind_stderr_report).

    The binary's own stdout is discarded — output correctness was already
    verified. Only the Valgrind stderr report matters here.
    """
    cmd = _VALGRIND_FLAGS + [binary]
    vg_timeout = base_timeout * _VG_TIMEOUT_FACTOR
    try:
        with open(input_path, "r", encoding="utf-8", errors="replace") as fh:
            result = subprocess.run(
                cmd,
                stdin=fh,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                timeout=vg_timeout,
            )
        return (result.returncode == 0, result.stderr)
    except subprocess.TimeoutExpired:
        return (False, f"[autotest] Valgrind timed out after {vg_timeout:.0f}s.")
    except FileNotFoundError:
        return (False, "[autotest] valgrind binary not found.")


# ══════════════════════════════════════════════════════════════════════════════
# § 7 · OUTPUT COMPARISON
# ══════════════════════════════════════════════════════════════════════════════

def _normalise(text: str) -> List[str]:
    """
    Strips trailing whitespace per line and uses splitlines() so a missing
    final newline does not produce a spurious trailing empty string.
    This eliminates the single most common source of false failures in
    academic graders.
    """
    return [line.rstrip() for line in text.splitlines()]


def compare_outputs(actual: str, expected: str) -> Tuple[bool, str]:
    """
    Returns (match, unified_diff_string).
    fromfile='expected', tofile='actual': '-' lines = expected, '+' = actual.
    """
    a = _normalise(actual)
    e = _normalise(expected)
    if a == e:
        return (True, "")
    diff = difflib.unified_diff(e, a, fromfile="expected", tofile="actual",
                                lineterm="", n=3)
    return (False, "\n".join(diff))


# ══════════════════════════════════════════════════════════════════════════════
# § 8 · GIT WORKFLOW
# ══════════════════════════════════════════════════════════════════════════════

def _git(args: List[str]) -> Tuple[int, str]:
    """
    Runs a git subcommand. Returns (returncode, merged_output).
    Never raises; all exceptions are converted to a non-zero returncode.
    """
    try:
        r = subprocess.run(
            ["git"] + args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        return (r.returncode, r.stdout.strip())
    except FileNotFoundError:
        return (127, "git not found. Install: sudo apt install git")
    except OSError as exc:
        return (1, f"OS error: {exc}")


def run_git_workflow(commit_message: str) -> GitResult:
    """
    Executes: git add .  →  git commit  →  git push

    Design decisions:
    - Each step is gated on the previous step's success.
    - 'Nothing to commit' is treated as a non-fatal advisory so running
      autotest on an unchanged file does not erroneously abort the push.
    - All captured output is preserved for the printer layer.
    """
    gr = GitResult(attempted=True, commit_msg=commit_message)

    # Pre-flight: verify we are inside a Git repository.
    code, _ = _git(["rev-parse", "--is-inside-work-tree"])
    if code != 0:
        gr.error = "Current directory is not inside a Git repository."
        return gr

    # ── git add . ─────────────────────────────────────────────────────────
    code, out   = _git(["add", "."])
    gr.add_out  = out
    gr.add_ok   = (code == 0)
    if not gr.add_ok:
        gr.error = f"git add failed (exit {code})."
        return gr

    # ── git commit ────────────────────────────────────────────────────────
    full_msg      = f"[Autotest] {commit_message}"
    code, out     = _git(["commit", "-m", full_msg])
    gr.commit_out = out
    gr.commit_ok  = (code == 0)

    if not gr.commit_ok:
        low = out.lower()
        if "nothing to commit" in low or "nothing added to commit" in low:
            gr.commit_ok = True   # advisory — not a real error
        else:
            gr.error = f"git commit failed (exit {code})."
            return gr

    # ── git push ──────────────────────────────────────────────────────────
    code, out   = _git(["push"])
    gr.push_out = out
    gr.push_ok  = (code == 0)
    if not gr.push_ok:
        gr.error = f"git push failed (exit {code})."

    return gr


# ══════════════════════════════════════════════════════════════════════════════
# § 9 · PRINTING UTILITIES
# ══════════════════════════════════════════════════════════════════════════════

_BAR    = "─" * 64
_INDENT = "   "


def _sep() -> None:
    print(c_dim(_BAR))


def print_banner(source: str, lang: str) -> None:
    print()
    print(c_header("╔══ autotest v2 ════════════════════════════════════════════════╗"))
    print(c_header("║  ") + c_bold(f"Target : {source:<54}") + c_header("║"))
    print(c_header("║  ") + c_bold(f"Lang   : {lang:<54}") + c_header("║"))
    print(c_header("╚═══════════════════════════════════════════════════════════════╝"))
    print()


def print_compilation_failure(output: str) -> None:
    print(c_fail("✗  Compilation failed\n"))
    for line in output.strip().splitlines():
        print(f"{_INDENT}{colorize(line, _C.RED)}")
    print()


def _render_diff(diff: str) -> None:
    print(c_info(f"{_INDENT}── diff  (─ expected  /  + actual) ──"))
    for line in diff.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            print(c_dim(f"{_INDENT}{line}"))
        elif line.startswith("+"):
            print(c_ok(f"{_INDENT}{line}"))
        elif line.startswith("-"):
            print(c_fail(f"{_INDENT}{line}"))
        elif line.startswith("@@"):
            print(c_info(f"{_INDENT}{line}"))
        else:
            print(c_dim(f"{_INDENT}{line}"))
    print()

def _render_valgrind_log(log: str) -> None:
    print(c_fail(f"{_INDENT}── Valgrind Whisperer ──"))
    
    lines = log.strip().splitlines()
    important_lines = []
    
    for line in lines:
        clean_line = re.sub(r'^==\d+==\s*', '', line)
        low = clean_line.lower()
        
        # Skip annoying generic Valgrind startup/shutdown messages
        if any(k in low for k in ("memcheck", "rerun with", "valgrind-", "copyright")):
            continue
            
        # Grab the actual exact error descriptions (like "definitely lost")
        if "lost:" in low or "uninit" in low or "invalid" in low or "error summary:" in low:
            important_lines.append(c_fail(f"{_INDENT}✗ {clean_line}"))
        
        # Grab the exact file and line number
        elif ".cpp:" in low or ".c:" in low or ".h:" in low:
            match = re.search(r'([a-zA-Z0-9_-]+\.[cph]+:\d+)', clean_line)
            if match:
                important_lines.append(c_warn(f"{_INDENT}  → Found at: {match.group(1)}"))

    if important_lines:
        for line in important_lines:
            print(line)
    else:
        for line in lines[-5:]:
            print(c_dim(f"{_INDENT}{line}"))
    print()

def print_test_result(r: TestResult, index: int, total: int) -> None:
    idx  = c_dim(f"[{index}/{total}]")
    name = c_bold(r.test.name)
    ms   = c_dim(f"  {r.runtime_secs * 1000:.1f}ms")

    if r.timed_out:
        print(f"  {c_fail('✗  TIMEOUT')}  {idx} {name}{ms}")
        print(c_warn(f"{_INDENT}Exceeded time limit ({r.runtime_secs:.1f}s)."))
        print(c_dim( f"{_INDENT}Likely cause: infinite loop or blocking read."))
        print()
        return

    if r.passed:
        mem = ""
        if r.mem_ok is True:
            mem = f"  {c_ok('✓ memcheck')}"
        elif r.mem_ok is False:
            mem = f"  {c_fail('✗ memleak')}"
        print(f"  {c_ok('✓  PASS')}     {idx} {name}{ms}{mem}")
        if r.mem_ok is False:
            _render_valgrind_log(r.valgrind_log)
    else:
        print(f"  {c_fail('✗  FAIL')}     {idx} {name}{ms}")
        if r.error_message:
            print(c_warn(f"{_INDENT}Runtime stderr:"))
            for line in r.error_message.strip().splitlines():
                print(c_fail(f"{_INDENT}{line}"))
            print()
        if r.unified_diff:
            _render_diff(r.unified_diff)


def print_git_result(gr: GitResult) -> None:
    print()
    _sep()
    print(c_git("  GIT WORKFLOW"))
    _sep()

    # Pre-flight / add failure
    if gr.error and not gr.add_ok:
        print(c_fail(f"  ✗  Aborted — {gr.error}"))
        if gr.add_out:
            print(c_dim(f"{_INDENT}{gr.add_out}"))
        print()
        return

    add_icon = c_ok("✓") if gr.add_ok else c_fail("✗")
    print(f"  {add_icon}  git add .")

    nothing = "nothing to commit" in gr.commit_out.lower()
    if nothing:
        print(f"  {c_warn('–')}  git commit  "
              f"{c_warn('(nothing to commit — working tree clean)')}")
    else:
        commit_icon = c_ok("✓") if gr.commit_ok else c_fail("✗")
        label = c_bold(f"[Autotest] {gr.commit_msg}")
        print(f"  {commit_icon}  git commit -m \"{label}\"")
        if gr.commit_out:
            first = gr.commit_out.splitlines()[0]
            print(c_dim(f"{_INDENT}{first}"))

    if gr.commit_ok:
        push_icon = c_ok("✓") if gr.push_ok else c_fail("✗")
        print(f"  {push_icon}  git push")
        for line in gr.push_out.strip().splitlines():
            print(c_dim(f"{_INDENT}{line}"))
        if not gr.push_ok and gr.error:
            print(c_fail(f"{_INDENT}{gr.error}"))

    print()


def print_summary(
    results: List[TestResult],
    vg_was_used: bool,
    is_cpp: bool,
    gr: Optional[GitResult],
) -> None:
    total    = len(results)
    passed   = sum(1 for r in results if r.passed)
    failed   = total - passed
    mem_errs = sum(1 for r in results if r.mem_ok is False)

    print()
    _sep()
    print(c_bold("  SUMMARY"))
    _sep()

    p = c_ok(str(passed))
    f = c_fail(str(failed)) if failed else c_dim("0")
    print(f"  Tests   : {p} passed, {f} failed  /  {total} total")

    if is_cpp:
        if vg_was_used:
            ms = c_fail(f"{mem_errs} error(s)") if mem_errs else c_ok("clean")
            print(f"  Memory  : {ms}")
        else:
            print(f"  Memory  : {c_warn('skipped — Valgrind not installed')}")
            print(c_dim( "             sudo apt install valgrind"))

    if gr and gr.attempted:
        if gr.push_ok:
            gs = c_ok("add ✓  commit ✓  push ✓")
        elif gr.commit_ok:
            gs = c_warn("add ✓  commit ✓  push ✗")
        elif gr.add_ok:
            gs = c_warn("add ✓  commit ✗  push –")
        else:
            gs = c_fail("aborted")
        print(f"  Git     : {gs}")

    _sep()
    if failed == 0 and mem_errs == 0:
        print(c_ok("  ✓  All tests passed."))
    else:
        parts = []
        if failed:
            parts.append(f"{failed} I/O failure(s)")
        if mem_errs:
            parts.append(f"{mem_errs} memory error(s)")
        print(c_fail("  ✗  " + ",  ".join(parts) + "."))
    print()


# ══════════════════════════════════════════════════════════════════════════════
# § 10 · TEST ENGINE
# ══════════════════════════════════════════════════════════════════════════════

def execute_tests(
    run_cmd:      List[str],
    tests:        List[TestCase],
    timeout:      float,
    use_valgrind: bool,
    binary_path:  Optional[str],
) -> List[TestResult]:
    """
    Iterates all TestCases, runs the target program, optionally invokes
    Valgrind, and prints each result immediately (streaming output).

    Valgrind is only invoked when the I/O test passes: running it on an
    already-wrong execution path produces irrelevant noise.
    """
    results: List[TestResult] = []
    total = len(tests)

    for idx, test in enumerate(tests, start=1):
        # Load expected output ───────────────────────────────────────────
        try:
            with open(test.expected_path, "r", encoding="utf-8", errors="replace") as fh:
                expected = fh.read()
        except OSError as exc:
            r = TestResult(test=test, passed=False,
                           error_message=f"Cannot read expected file: {exc}")
            results.append(r)
            print_test_result(r, idx, total)
            continue

        # Run program ────────────────────────────────────────────────────
        exit_ok, actual, stderr, timed_out, elapsed = run_program(
            run_cmd, test.input_path, timeout
        )

        if timed_out:
            r = TestResult(test=test, passed=False,
                           timed_out=True, runtime_secs=elapsed)
            results.append(r)
            print_test_result(r, idx, total)
            continue

        # Compare ────────────────────────────────────────────────────────
        matched, diff = compare_outputs(actual, expected)
        error_msg     = stderr.strip() if (not exit_ok and stderr.strip()) else ""

        r = TestResult(
            test=test,
            passed=matched,
            actual_output=actual,
            expected_output=expected,
            unified_diff=diff,
            error_message=error_msg,
            runtime_secs=elapsed,
        )

        # Valgrind (C++ only, I/O-correct tests only) ────────────────────
        if use_valgrind and binary_path and matched:
            mem_clean, vg_log = run_valgrind(binary_path, test.input_path, timeout)
            r.mem_ok       = mem_clean
            r.valgrind_log = vg_log

        results.append(r)
        print_test_result(r, idx, total)

    return results


# ══════════════════════════════════════════════════════════════════════════════
# § 11 · CLI ARGUMENT PARSER
# ══════════════════════════════════════════════════════════════════════════════

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="autotest",
        description=(
            "Automated I/O and memory testing for C++ and Python assignments.\n"
            "Technion 234124-compliant: g++ -std=c++17 -Wall -pedantic-errors -Werror"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  autotest main.cpp
  autotest solution.py
  autotest main.cpp --save "Implement queue with O(1) ops"
  autotest main.cpp --tests-dir ./cases --timeout 10
  autotest main.cpp --no-valgrind --no-color
        """,
    )
    parser.add_argument("source",
                        help="Source file to test (.cpp or .py)")
    parser.add_argument("--tests-dir", metavar="DIR", default="tests",
                        help="Directory with test pairs (default: ./tests)")
    parser.add_argument("--timeout", metavar="SEC", type=float, default=5.0,
                        help="Per-test wall-clock timeout in seconds (default: 5.0)")
    parser.add_argument(
        "--save", metavar="MSG",
        help='After all tests: git add . && git commit -m "[Autotest] MSG" && git push',
    )
    parser.add_argument("--no-valgrind", action="store_true",
                        help="Skip Valgrind memory checking (C++ only)")
    parser.add_argument("--no-color", action="store_true",
                        help="Disable ANSI colour output")
    return parser


# ══════════════════════════════════════════════════════════════════════════════
# § 12 · MAIN ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = _build_parser()
    args   = parser.parse_args()

    # Colour toggle ──────────────────────────────────────────────────────────
    global _COLOR_ENABLED
    if args.no_color:
        _COLOR_ENABLED = False

    source    = args.source
    tests_dir = args.tests_dir
    timeout   = args.timeout

    # Validate source file ───────────────────────────────────────────────────
    if not os.path.isfile(source):
        print(c_fail(f"[autotest] error: source file '{source}' not found."),
              file=sys.stderr)
        sys.exit(1)

    ext = os.path.splitext(source)[1].lower()
    if ext not in (".cpp", ".py"):
        print(c_fail(f"[autotest] error: unsupported extension '{ext}'. "
                     "Expected .cpp or .py"), file=sys.stderr)
        sys.exit(1)

    is_cpp = (ext == ".cpp")
    lang   = ("C++17  (g++ -Wall -pedantic-errors -Werror)"
               if is_cpp else "Python 3")

    print_banner(source, lang)

    # C++ compilation ────────────────────────────────────────────────────────
    binary_path: Optional[str] = None

    if is_cpp:
        print(c_info("Compiling …"))
        ok_flag, compiler_out = compile_cpp(source)

        if not ok_flag:
            print_compilation_failure(compiler_out)
            # Still honour --save: commit the broken state.
            gr: Optional[GitResult] = None
            if args.save is not None:
                gr = run_git_workflow(args.save)
                print_git_result(gr)
            sys.exit(1)

        binary_path = _BINARY_PATH

        # With -Werror any output is unusual; surface it explicitly.
        if compiler_out.strip():
            print(c_warn("Compiler note:"))
            for line in compiler_out.strip().splitlines():
                print(c_warn(f"{_INDENT}{line}"))
            print()

        print(c_ok("✓  Compilation successful\n"))

    # Discover tests ─────────────────────────────────────────────────────────
    tests = discover_tests(tests_dir)

    if not tests:
        print(c_warn(f"No test cases found in '{tests_dir}/'"))
        print(c_dim("  Supported formats:"))
        print(c_dim("    test1.in / test1.expected   ← Technion 234124 canonical"))
        print(c_dim("    test1.in / test1.out"))
        print(c_dim("    in_1.txt / out_1.txt"))
        if is_cpp:
            cleanup_binary()
        gr = None
        if args.save is not None:
            gr = run_git_workflow(args.save)
            print_git_result(gr)
        sys.exit(0)

    print(c_info(f"Found {len(tests)} test case(s) in '{tests_dir}/'"))
    _sep()

    # Build run command ───────────────────────────────────────────────────────
    run_cmd: List[str] = (
        [binary_path] if is_cpp
        else [sys.executable, source]   # same interpreter → respects venvs
    )

    # Valgrind availability ──────────────────────────────────────────────────
    vg_active = False
    if is_cpp and not args.no_valgrind:
        if valgrind_available():
            vg_active = True
        else:
            print(c_warn("Valgrind not found — memory checking disabled."))
            print(c_dim( "  Install: sudo apt install valgrind\n"))

    # Execute all tests ──────────────────────────────────────────────────────
    results = execute_tests(
        run_cmd=run_cmd,
        tests=tests,
        timeout=timeout,
        use_valgrind=vg_active,
        binary_path=binary_path,
    )

    # Git workflow (--save) ──────────────────────────────────────────────────
    # Runs regardless of pass/fail — always commit your work.
    gr = None
    if args.save is not None:
        gr = run_git_workflow(args.save)
        print_git_result(gr)

    # Summary ────────────────────────────────────────────────────────────────
    print_summary(results, vg_active, is_cpp, gr)

    # Cleanup ────────────────────────────────────────────────────────────────
    if is_cpp:
        cleanup_binary()

    # Exit code ──────────────────────────────────────────────────────────────
    # Non-zero on any I/O failure, memory error, or Git workflow failure.
    # This makes autotest composable in CI/shell pipelines.
    io_fail  = any(not r.passed      for r in results)
    mem_fail = any(r.mem_ok is False for r in results)
    git_fail = (gr is not None) and (not gr.push_ok)

    sys.exit(1 if (io_fail or mem_fail or git_fail) else 0)


if __name__ == "__main__":
    main()