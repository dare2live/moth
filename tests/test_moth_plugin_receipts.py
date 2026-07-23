import json
from pathlib import Path
import subprocess
import sys


def test_receipt_helper_supports_read_only_stdin_stdout_transport() -> None:
    helper = (
        Path(__file__).parents[1]
        / "plugins"
        / "moth"
        / "skills"
        / "moth"
        / "scripts"
        / "make_activation_receipts.py"
    )
    digest = "sha256:" + ("a" * 64)
    inspection = {
        "orchestration": {
            "decision_context": {
                "task": {"run_id": "run-stream"},
                "ordered_guidance_sources": ["mio"],
            },
            "guidance": {
                "sources": [
                    {
                        "id": "mio",
                        "state": "DISCOVERED",
                        "source_digest": digest,
                    }
                ]
            },
        }
    }

    result = subprocess.run(
        [
            sys.executable,
            str(helper),
            "--inspection",
            "-",
            "--output",
            "-",
            "--loaded-source",
            "mio",
        ],
        input=json.dumps(inspection),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    receipts = json.loads(result.stdout)
    assert receipts[0]["source_id"] == "mio"
    assert receipts[0]["run_id"] == "run-stream"
    assert receipts[0]["source_digest"] == digest
    assert result.stderr == ""
