import json

from filepilot.cli import main
from filepilot.demo import create_demo
from filepilot.scanner import scan_folder


def test_cli_scan_and_plan_are_read_only(folder, capsys):
    (folder / "a.txt").write_text("one")
    assert main(["scan", str(folder), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["read_only"] is True and payload["file_count"] == 1
    assert main(["plan", str(folder), "--json"]) == 0
    preview = json.loads(capsys.readouterr().out)
    assert len(preview["moves"]) == 1
    assert not (folder / "FilePilot_整理").exists()


def test_demo_content_is_generated_once_and_has_expected_duplicates(tmp_path):
    root = create_demo(tmp_path / "demo")
    result = scan_folder(root)
    assert len(result.files) == 15
    assert len(result.duplicates) == 3
    assert create_demo(root) == root
    assert len(scan_folder(root).files) == 15
