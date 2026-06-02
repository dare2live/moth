from moth.cli import main


def test_snapshot_emits_json_for_chunkymonkey(capsys) -> None:
    code = main(["snapshot", "--repo", "/Users/dp/Documents/M/stock/chunkymonkey", "--profile", "chunkymonkey", "--format", "json"])
    captured = capsys.readouterr()
    assert code == 0
    assert '"codegraph"' in captured.out
    assert '"complexity"' in captured.out


def test_doctor_passes_for_chunkymonkey(capsys) -> None:
    code = main(["doctor", "--repo", "/Users/dp/Documents/M/stock/chunkymonkey", "--profile", "chunkymonkey", "--format", "json"])
    captured = capsys.readouterr()
    assert code == 0
    assert '"warnings"' in captured.out


def test_sync_emits_sync_and_snapshot_json(capsys) -> None:
    code = main(["sync", "--repo", "/Users/dp/Documents/M/stock/chunkymonkey", "--profile", "chunkymonkey", "--format", "json"])
    captured = capsys.readouterr()
    assert code == 0
    assert '"sync"' in captured.out
    assert '"snapshot"' in captured.out
