from moth.output_transport import persist_optional_output


def test_stdout_sentinel_never_becomes_a_file(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)

    persist_optional_output("-", '{"status":"PASS"}\n')

    assert not (tmp_path / "-").exists()


def test_file_target_persists_rendered_output(tmp_path) -> None:
    target = tmp_path / "nested" / "inspection.json"

    persist_optional_output(str(target), '{"status":"PASS"}\n')

    assert target.read_text(encoding="utf-8") == '{"status":"PASS"}\n'
