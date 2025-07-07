#!/usr/bin/env python
"""
Annotate GoogleTest / GoogleMock unit tests in C++ sources.

For every TEST/TEST_F/TEST_P/TEST_SUITE that is *not* already
preceded by a // comment, the script asks a local Ollama model
for "ONE concise sentence" describing what the test verifies
and inserts that comment right above the macro invocation.
"""
import argparse, os, pathlib, re, requests, textwrap, sys, time, statistics

START_OVERALL = time.perf_counter()
llm_durations = []          # one entry per test
file_stats     = {}         # path -> [num_tests, seconds]

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
MODEL       = os.getenv("MODEL_NAME",  "qwen3:4b")

# Regex that matches the first line of a GoogleTest macro.
MACRO_RE = re.compile(r"""
    ^\s*                                   # optional indentation
    (TEST|TEST_F|TEST_P|TEST_SUITE|TYPED_TEST)        # macro names
    \s*\(.*\)\s*                           # '(Fixture, Name)'
    (?:;)?\s*$                             # possible semicolon for TEST_SUITE
""", re.VERBOSE)

def llm_summarise(code: str) -> str:
    prompt = (
        "You summarise C++ GoogleTest cases for a Way-of-Work assessment. "
                "Return ONE plain-English sentence, ≤100 characters. "
                "Do NOT mention fixture or test names. "
                "Do NOT emit tags, markup, or commentary. "
                "Output the sentence only"
        "### Instruction: In ONE SHORT sentence  *only* (up to 100 symbols), say what this C++ "
        "GoogleTest verifies. I need it for the Way of Work assesment."
        "Use plain English; do not mention fixture or test names."
        "Provide nothing except of pure description of what this test do"
        "Do NOT include <think> blocks, explanations or tags \n\n"
        f"```cpp\n{code}\n```\n\n### Answer:\n"
    )

    t0 = time.perf_counter()

    r = requests.post(
        f"{OLLAMA_HOST}/api/generate",
        json={
            "model": MODEL,
            "prompt": prompt,
            "stream": False,
            "temperature": 0.1,
            "top_p": 0.9,
            "max_tokens": 64,
        },
        timeout=3000,
        stream=True
    )
    r.raise_for_status()
    raw = r.json()["response"]
    clean = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL)
    clean = re.sub(r"</?[^>]+>", "", clean)
    summary = " ".join(clean.strip().split())
    
    llm_durations.append(time.perf_counter() - t0)
    return summary

def find_test_blocks(lines):
    """
    Yields (macro_start_line_index, macro_end_line_index_exclusive)
    for every TEST* macro body found.

    The end is determined by counting braces after the opening '{'.
    """
    i = 0
    while i < len(lines):
        if MACRO_RE.match(lines[i]):
            # scan forward to first '{'
            j = i
            while j < len(lines) and '{' not in lines[j]:
                j += 1
            if j == len(lines):
                break   # malformed file
            brace_depth = 0
            k = j
            while k < len(lines):
                brace_depth += lines[k].count('{')
                brace_depth -= lines[k].count('}')
                if brace_depth == 0:
                    yield (i, k + 1)
                    i = k
                    break
                k += 1
        i += 1

def annotate_file(path: pathlib.Path):
    t_file = time.perf_counter()

    lines = path.read_text(encoding="utf-8").splitlines()
    added = 0

    # Walk backwards so line-number shifts don’t affect upcoming indices.
    for start, _ in reversed(list(find_test_blocks(lines))):
        # Find previous non-blank line
        prev = start - 1
        while prev >= 0 and not lines[prev].strip():
            prev -= 1
        already_has_comment = (
            prev >= 0 and (
                lines[prev].lstrip().startswith("//")   # single-line
                or lines[prev].lstrip().startswith("/*")  # block comment start
                or lines[prev].lstrip().startswith("*")
            )
        )
        if already_has_comment:
            continue

        # Extract test body for context (max 200 lines).
        context = "\n".join(lines[start : min(start + 200, len(lines))])
        summary = llm_summarise(context)
        indent = ' ' * (len(lines[start]) - len(lines[start].lstrip()))
        wrapped = textwrap.wrap(summary, width=100 - len(indent) - 3)

        comment_lines = [f"{indent}/*"]                     # opening line
        for line in wrapped:
            comment_lines.append(f"{indent} * {line}")      # body lines
        comment_lines.append(f"{indent} */")                # closing line

        comment = "\n".join(comment_lines)
        print("----")
        print(comment)
        print("----")
        lines.insert(start, comment)
        added += 1

    if added:
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        elapsed = time.perf_counter() - t_file
        file_stats[path.name] = [added, elapsed]
        print(f"✔ {added} test(s) annotated in {path}  ({elapsed:,.2f} s)")   
    else:
        print(f"- {path}: nothing to annotate")

def collect_cpp_files(paths):
    """Return a de-duplicated list of *.cpp files for every argument."""
    seen = set()
    out  = []
    for p in paths:
        path = pathlib.Path(p).resolve()
        if path.is_file() and path.suffix == ".cpp":
            if path not in seen:
                out.append(path);  seen.add(path)
        elif path.is_dir():
            for f in path.rglob("*.cpp"):
                if f not in seen:
                    out.append(f);  seen.add(f)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target", help="C++ file or directory")
    args = ap.parse_args()

    target = pathlib.Path(args.target).resolve()
    files = [target] if target.is_file() else list(target.rglob("*.cpp"))
    if not files:
        sys.exit("No *.cpp files found")

    for f in files:
        annotate_file(f)

if __name__ == "__main__":
    main()

    total_time = time.perf_counter() - START_OVERALL
    total_tests = sum(n for n, _ in file_stats.values())

    if total_tests:
        print("\n──── Benchmark ──────────────────────────────────────")
        for fname, (n, sec) in file_stats.items():
            print(f"  {fname:30}  {n:4} tests  {sec:7.2f} s  "
                  f"({sec/n:5.2f} s avg)")

        print("  ───────────────────────────────────────────────────")
        print(f"  TOTAL: {total_tests} tests in {len(file_stats)} files")
        print(f"         LLM time   : {sum(llm_durations):7.2f} s  "
              f"(avg {statistics.mean(llm_durations):.2f} s)")
        print(f"         Wall clock : {total_time:7.2f} s\n")

