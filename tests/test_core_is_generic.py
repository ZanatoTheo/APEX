"""Nothing in apex/ outside env_connector/ may talk about the test. To change the task, only the connector and environment/ may change."""
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORDS = re.compile(r"\bprices?\b|market|asset|trad(e|ing)|portfolio|backtest|wayback|benchmark|ticker|\bstocks?\b"
                   r"|crypto|invest|financ|ohlc|\bbuy\b|\bsell\b", re.I)
SUFFIXES = {".py", ".md", ".txt", ".json", ".toml", ".yaml", ".yml", ".j2", ".tmpl"}


def scan_for_test_words(root: Path) -> list[str]:
    hits = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if not path.is_file() or path.suffix not in SUFFIXES:
            continue
        if "env_connector" in rel.parts or "__pycache__" in rel.parts:
            continue
        for n, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
            if WORDS.search(line):
                hits.append(f"{rel}:{n}: {line.strip()}")
    return hits


# 6
def test_core_is_generic():
    assert scan_for_test_words(ROOT / "apex") == []


def test_scan_catches_a_planted_word(tmp_path):
    copy = tmp_path / "apex"
    shutil.copytree(ROOT / "apex", copy, ignore=shutil.ignore_patterns("__pycache__"))
    with open(copy / "config.py", "a") as f:
        f.write("# portfolio\n")
    (copy / "env_connector").mkdir(exist_ok=True)
    (copy / "env_connector" / "x.py").write_text("# backtest the portfolio\n")
    hits = scan_for_test_words(copy)
    assert len(hits) == 1 and hits[0].startswith("config.py:")


def test_scan_reads_prompt_files_too(tmp_path):
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "agent.md").write_text("Pick stocks to buy.\n")
    assert len(scan_for_test_words(tmp_path)) == 1
