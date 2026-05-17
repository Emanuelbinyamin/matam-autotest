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
