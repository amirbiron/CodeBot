import os
from pathlib import Path

from refactoring_engine import RefactoringEngine, RefactorType

INPUT_FILE = "/workspace/tmp/monolith_input.py"
OUTPUT_DIR = "/workspace/tmp/mega_monolith_split"


def main() -> None:
    Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        code = f.read()
    eng = RefactoringEngine()
    res = eng.propose_refactoring(code=code, filename="mega_monolith.py", refactor_type=RefactorType.SPLIT_FUNCTIONS)
    if not res.success or not res.proposal:
        raise SystemExit(f"Refactor failed: {res.error}")
    for fn, content in res.proposal.new_files.items():
        out_path = os.path.join(OUTPUT_DIR, fn)
        with open(out_path, "w", encoding="utf-8") as wf:
            wf.write(content)
    print("Wrote:")
    for fn in sorted(res.proposal.new_files.keys()):
        print(os.path.join(OUTPUT_DIR, fn))


if __name__ == "__main__":
    main()
