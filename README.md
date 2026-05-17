# 🐉 Matam Auto-Test (Technion 234124)

A robust, zero-dependency CLI testing utility built specifically for **Introduction to Systems Programming (234124)** at the Technion. 

Stop wrestling with massive walls of Valgrind text, forgetting compilation flags, and messing up your Git workflow. `autotest` handles compilation, I/O diffing, memory checking, concurrency, and version control in a single command.

## ✨ Features

* **Strict Academic Compilation:** Automatically compiles C++ using the exact course flags: `-std=c++17 -Wall -pedantic-errors -Werror -g`.
* **Auto-Makefile Detection:** If a `Makefile` is present in your directory, it intelligently runs `make` instead of raw `g++`.
* **The Valgrind Whisperer:** Automatically runs `valgrind` in the background, strips away the garbage output, and highlights the exact line number of your memory leaks in clean, readable text.
* **Smart I/O Diffing:** Compares your output against `.expected` files and generates color-coded visual diffs with character-level accuracy so you can see exactly where you missed a space or a newline.
* **Concurrency Engine:** Executes tests in parallel via an asynchronous pool while preserving a clean, sequential real-time streaming output UI.
* **Adaptive Timeout Scaling:** Dynamically extends timeout thresholds when memory tracking hooks are active to completely eliminate execution race conditions or False-Positives.
* **Git Auto-Save:** Pass the `--save` flag to automatically `add`, `commit`, and `push` your code after a test run.
* **Moodle Submitter:** Pass the `--pack <ID>` flag to safely bundle verified workspace files into a submission-ready archive, actively blocking corrupted or leaking code from being packed.

## 🚀 Installation (WSL / Linux)

Since the tool uses only Python 3 standard libraries, there is nothing to `pip install`. 

1. Clone this repository anywhere on your machine:
   ```bash
   git clone [https://github.com/Emanuelbinyamin/matam-autotest.git](https://github.com/Emanuelbinyamin/matam-autotest.git) ~/matam-autotest
---

# 🐉 Matam Auto-Test (v5.0 Asynchronous Production-Ready)

A highly optimized, zero-dependency asynchronous CLI testing utility engineered specifically for **Introduction to Systems Programming (234124)** at the Technion.

The tool automates the entire local verification lifecycle: strict academic compilation, concurrent multi-test execution, character-level visual diffing, isolated dynamic memory analysis (Valgrind noise-filtering), clean repository version control, and automated Moodle submission packaging.

---

## 📂 Required Workspace Architecture

For the script to dynamically discover your test cases, compile targets, and bundle archives, your assignment directory must adhere to the following layout:

```text
my_homework_dir/
├── Makefile  (or makefile - Optional, fallback to raw g++ compilation)
├── main.cpp
├── array.cpp
├── array.h
├── dry.pdf   (Optional submission document)
└── tests/    (Must be named exactly 'tests' unless overridden via --tests-dir)
    ├── test1.in
    ├── test1.expected
    ├── test2.in
    ├── test2.expected
    └── test3.in
    └── test3.expected

```

* **Test Pair Invariance:** A test scenario is only registered if both a `.in` file and a matching `.expected` file exist with identical numeric indexes (e.g., `test1.in` and `test1.expected`).

---

## 🛠️ CLI Execution Manual

Once the global alias `autotest` is configured in your terminal session, use the following operational interface patterns:

### 1. Standard Asynchronous Execution

Runs all discovered tests concurrently, automatically utilizing the maximum number of CPU core workers available. Memory auditing via Valgrind is spawned implicitly for passing logical sequences.

```bash
autotest main.cpp

```

### 2. Manual Concurrency Control

Restricts the internal thread pool to a set threshold of parallel workers. Ideal for resource-constrained environments or preventing CPU starvation.

```bash
autotest main.cpp --workers 2

```

### 3. Full Production Automation (Test + Cloud Save + Moodle Package)

Executes all verifications concurrently. If (and only if) every test yields a perfect logic match and an absolute clean memory profile, the tool scrubs binary artifacts via `make clean`, pushes source files to GitHub, and generates a clean `<ID>.zip` for immediate Moodle upload.

```bash
autotest main.cpp --save "Implemented array expansion" --pack 123456789

```

### 4. Fast Logic Smoke-Testing

Skips the expensive Valgrind execution phase to quickly iterate and verify program logic transformations.

```bash
autotest main.cpp --no-valgrind

```

---

## 📊 Deciphering the Terminal Output UI

The streaming output engine utilizes an ordered-drain architecture: executions are completely parallelized, but the interface prints results in strict sequential order (`test1` to `testN`) to prevent UI text corruption.

### The Component View blocks:

#### A. Compilation Header

```text
╔══ autotest v5 ════════════════════════════════════════════════╗
║  Target : main.cpp                                            ║
╚═══════════════════════════════════════════════════════════════╝
Compiling…
   → Makefile detected — running 'make'...
✓ Compilation successful

```

* **Behavior:** The compiler parses your `Makefile` to deduce target variables (`EXEC`, `TARGET`, `BIN`, `PROG`). If absent, it invokes direct compilation via `g++` with strict standard flags: `-std=c++17 -Wall -pedantic-errors -Werror -g`.

#### B. Asynchronous Streaming Matrix

```text
  ✓ PASS [1/6] test1  2.5ms  ✓ memcheck
  ✗ FAIL [2/6] test2  4.1ms

```

* **Metrics:** Each line displays real-time execution duration in milliseconds along with a dedicated `✓ memcheck` or `✗ memleak` banner tracking live memory operations.

#### C. Character-Level Inline Diff Engine

When a logical mismatch is caught, the tool suppresses standard block diffs and applies character-level highlighting via an intra-line tokenizer:

```text
   ── diff  (─ expected  /  + actual) ──
   -Hello·World
   +Hello··World

```

* **Symbols:** Invisible whitespace variations are translated into explicit glyphs (`" "` $\rightarrow$ `·`, `"\t"` $\rightarrow$ `→`) inside background spans so trailing or double space variations can never be missed.

#### D. The Valgrind Whisperer Report

If logical assertions pass but memory errors or initialization leaks occur, the raw heap logs are filtered into semantic alerts:

```text
   ── Valgrind report ──
   ✗ 40 bytes in 1 blocks are definitely lost in loss record 1 of 1
     → array.cpp:7

```

* **Trace Isolation:** The parser scans frame references and explicitly displays the file name and precise source line number (`array.cpp:7`) responsible for the allocation leak.

---

## 🧠 The "What to do if..." Troubleshooting Matrix

| Scenario / Error | Root Cause Analysis | Corrective Action Blueprint |
| --- | --- | --- |
| **`✗ Compilation failed` followed by wall of syntax errors** | Your source code violates strict ISO C++17 rules, holds unhandled warnings, or contains language extensions banned by `-pedantic-errors`. | Correct the errors reported by `g++`. Ensure you are not utilizing non-standard methods or compiler extensions. |
| **`✗ Binary not found at ... after compilation.`** | A `Makefile` is present, but it compiled the binary with a custom name that does not match the standard variables `EXEC`, `TARGET`, `BIN`, or `PROG`. | Open your `Makefile` and ensure the final executable variable name is explicitly declared using one of the recognized terms (e.g., `EXEC = main`). |
| **`✗ FAIL ...` displaying red blocks covering spaces (`·`)** | The output logic matches words, but contains a trailing space, mismatched double-spacing, or an incorrect newline boundary. | Look closely at the `+` line. The character `·` indicates exactly where your program printed an unneeded whitespace. Adjust your output stream `std::cout` loops. |
| **`✗ memleak` along with a Valgrind trace** | An allocation made via `new` or `new[]` was never scrubbed via a corresponding `delete` or `delete[]`, or your program accessed uninitialized memory branches. | Navigate to the exact source file line highlighted by the arrow (`→ file.cpp:line`). Ensure your class destructor properly handles dynamic cleanup across all conditional returns. |
| **`✗ TIMEOUT`** | Your code entered an infinite logical loop (`while(true)`), hit a thread deadlock, or is hung waiting for an EOF input stream block. | Check your `while(std::cin >> ...)` loop conditions. Ensure your exit boundaries are properly triggered when the input stream runs dry. |
| **`✗ Not a Git repository.` inside the Git workflow block** | You passed the `--save` parameter, but the current working directory has not been initialized with an underlying Git layout. | Run `git init` or move your working directory inside your managed homework repository before invoking cloud automation flags. |
| **Moodle Packager displays: `✗ Tests failed — packing aborted**` | You passed the `--pack <ID>` flag, but at least one test failed due to a logical mismatch or a memory leak. | **System Intentional Guard:** The script physically blocks you from packing bad code to save your grade. Fix the underlying logical failure or memory leak, re-run, and the zip will compile automatically. |
