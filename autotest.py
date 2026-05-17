#!/usr/bin/env python3
import argparse, difflib, os, re, subprocess, sys, time
from dataclasses import dataclass
from typing import List, Optional, Tuple

class _C:
    RESET, BOLD, DIM, RED, GREEN, YELLOW, CYAN, MAGENTA, BLUE = "\033[0m", "\033[1m", "\033[2m", "\033[91m", "\033[92m", "\033[93m", "\033[96m", "\033[95m", "\033[94m"

def colorize(t, *codes): return "".join(codes) + t + _C.RESET
def c_ok(t): return colorize(t, _C.BOLD, _C.GREEN)
def c_fail(t): return colorize(t, _C.BOLD, _C.RED)
def c_warn(t): return colorize(t, _C.BOLD, _C.YELLOW)
def c_info(t): return colorize(t, _C.BOLD, _C.CYAN)
def c_header(t): return colorize(t, _C.BOLD, _C.MAGENTA)
def c_git(t): return colorize(t, _C.BOLD, _C.BLUE)
def c_dim(t): return colorize(t, _C.DIM)
def c_bold(t): return colorize(t, _C.BOLD, "\033[97m")

@dataclass
class TestCase: name: str; input_path: str; expected_path: str
@dataclass
class TestResult: test: TestCase; passed: bool; actual_output: str = ""; expected_output: str = ""; unified_diff: str = ""; error_message: str = ""; timed_out: bool = False; runtime_secs: float = 0.0; mem_ok: Optional[bool] = None; valgrind_log: str = ""
@dataclass
class GitResult: attempted: bool = False; add_ok: bool = False; commit_ok: bool = False; push_ok: bool = False; commit_msg: str = ""; add_out: str = ""; commit_out: str = ""; push_out: str = ""; error: str = ""

def discover_tests(tests_dir: str) -> List[TestCase]:
    if not os.path.isdir(tests_dir): return []
    files = set(os.listdir(tests_dir))
    tests, seen = [], set()
    a_in = {int(m.group(1)): f for f in files if (m := re.match(r"^test(\d+)\.in$", f))}
    a_exp = {int(m.group(1)): f for f in files if (m := re.match(r"^test(\d+)\.expected$", f))}
    for num in sorted(set(a_in) & set(a_exp)):
        tests.append(TestCase(f"test{num}", os.path.join(tests_dir, a_in[num]), os.path.join(tests_dir, a_exp[num])))
        seen.add(f"test{num}")
    return tests

_CPP_FLAGS = ["g++", "-std=c++17", "-Wall", "-pedantic-errors", "-Werror", "-g"]
_BINARY_PATH = "/tmp/autotest_binary"

def compile_cpp(source_path: str) -> Tuple[bool, str, str]:
    if os.path.exists("Makefile") or os.path.exists("makefile"):
        print(c_info("   → Makefile detected! Running 'make'..."))
        try:
            res = subprocess.run(["make"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            return (res.returncode == 0, res.stdout, f"./{os.path.splitext(source_path)[0]}")
        except FileNotFoundError: return (False, "make not found", "")
    else:
        try:
            res = subprocess.run(_CPP_FLAGS + [source_path, "-o", _BINARY_PATH], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            return (res.returncode == 0, res.stdout, _BINARY_PATH)
        except FileNotFoundError: return (False, "g++ not found", "")

def run_program(cmd, in_path, tout):
    try:
        with open(in_path, "r", encoding="utf-8") as fh:
            t0 = time.monotonic()
            p = subprocess.run(cmd, stdin=fh, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=tout)
            return (p.returncode == 0, p.stdout, p.stderr, False, time.monotonic() - t0)
    except subprocess.TimeoutExpired: return (False, "", "", True, tout)

def run_valgrind(binary, in_path, tout):
    try:
        with open(in_path, "r", encoding="utf-8") as fh:
            res = subprocess.run(["valgrind", "--leak-check=full", "--show-leak-kinds=all", "--track-origins=yes", "--error-exitcode=1", binary], stdin=fh, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=tout*15)
        return (res.returncode == 0, res.stderr)
    except subprocess.TimeoutExpired: return (False, "Valgrind timed out")

def run_git_workflow(msg) -> GitResult:
    gr = GitResult(attempted=True, commit_msg=msg)
    if subprocess.run(["git", "rev-parse"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0:
        gr.error = "Not a Git repo."; return gr
    gr.add_ok = subprocess.run(["git", "add", "."], capture_output=True).returncode == 0
    r_commit = subprocess.run(["git", "commit", "-m", f"[Autotest] {msg}"], capture_output=True, text=True)
    gr.commit_ok = (r_commit.returncode == 0 or "nothing to commit" in r_commit.stdout.lower())
    if gr.commit_ok:
        r_push = subprocess.run(["git", "push"], capture_output=True, text=True)
        gr.push_ok, gr.push_out = (r_push.returncode == 0, r_push.stderr or r_push.stdout)
    return gr

def execute_tests(cmd, tests, tout, use_vg, bin_path):
    results = []
    for idx, t in enumerate(tests, 1):
        with open(t.expected_path, "r", encoding="utf-8") as fh: expected = fh.read()
        ok, out, err, timed_out, elaps = run_program(cmd, t.input_path, tout)
        if timed_out:
            print(f"  {c_fail('✗ TIMEOUT')} [{idx}/{len(tests)}] {c_bold(t.name)}"); results.append(TestResult(t, False, timed_out=True)); continue
        
        a, e = [l.rstrip() for l in out.splitlines()], [l.rstrip() for l in expected.splitlines()]
        match = (a == e)
        diff = "\n".join(difflib.unified_diff(e, a, fromfile="expected", tofile="actual", lineterm="", n=3))
        r = TestResult(t, match, out, expected, diff, err, runtime_secs=elaps)
        
        if use_vg and bin_path and match: r.mem_ok, r.valgrind_log = run_valgrind(bin_path, t.input_path, tout)
        mem = f"  {c_ok('✓ memcheck')}" if r.mem_ok is True else f"  {c_fail('✗ memleak')}" if r.mem_ok is False else ""
        print(f"  {c_ok('✓ PASS') if match else c_fail('✗ FAIL')} [{idx}/{len(tests)}] {c_bold(t.name)} {elaps*1000:.1f}ms{mem}")
        
        if not match:
            print(c_info("   ── diff (─ expected / + actual) ──"))
            for l in diff.splitlines(): print(c_ok(f"   {l}") if l.startswith('+') and not l.startswith('+++') else c_fail(f"   {l}") if l.startswith('-') and not l.startswith('---') else c_dim(f"   {l}"))
        elif r.mem_ok is False:
            print(c_fail("   ── Valgrind Whisperer ──"))
            for line in r.valgrind_log.strip().splitlines():
                cl = re.sub(r'^==\d+==\s*', '', line)
                if any(k in cl.lower() for k in ("lost:", "uninit", "invalid", "error summary:")): print(c_fail(f"   ✗ {cl}"))
                elif m := re.search(r'([a-zA-Z0-9_-]+\.[cph]+:\d+)', cl): print(c_warn(f"     → Found at: {m.group(1)}"))
        results.append(r)
    return results

def main():
    p = argparse.ArgumentParser()
    p.add_argument("source"); p.add_argument("--save"); p.add_argument("--no-valgrind", action="store_true")
    args = p.parse_args()
    
    print(c_header(f"\n╔══ autotest v2 ════════════════════════════════════════════════╗\n║  Target : {args.source:<54}║\n╚═══════════════════════════════════════════════════════════════╝\n"))
    
    bin_path = None
    if args.source.endswith(".cpp"):
        print(c_info("Compiling …"))
        ok, out, bin_path = compile_cpp(args.source)
        if not ok:
            print(c_fail("✗ Compilation failed\n"))
            for l in out.strip().splitlines(): print(c_fail(f"   {l}"))
            sys.exit(1)
        print(c_ok("✓ Compilation successful\n"))

    tests = discover_tests("tests")
    if not tests: print(c_warn("No test cases found in 'tests/'")); sys.exit(0)
    
    vg = args.source.endswith(".cpp") and not args.no_valgrind and subprocess.run(["which", "valgrind"], stdout=subprocess.DEVNULL).returncode == 0
    res = execute_tests([bin_path] if args.source.endswith(".cpp") else [sys.executable, args.source], tests, 5.0, vg, bin_path)
    
    if args.save:
        gr = run_git_workflow(args.save)
        print(c_git("\n  GIT WORKFLOW\n" + "─"*64))
        print(f"  {'✓' if gr.add_ok else '✗'} git add .")
        if gr.commit_ok: print(f"  ✓ git commit -m \"[Autotest] {gr.commit_msg}\"")
        if gr.push_ok: print("  ✓ git push")
    
    if bin_path and bin_path == _BINARY_PATH and os.path.exists(bin_path): os.remove(bin_path)
    sys.exit(1 if any(not r.passed or r.mem_ok is False for r in res) else 0)

if __name__ == "__main__": main()
