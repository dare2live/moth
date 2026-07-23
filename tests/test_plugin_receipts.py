import json
import subprocess
import sys
from pathlib import Path


SCRIPT = (
    Path(__file__).parents[1]
    / "plugins"
    / "moth"
    / "skills"
    / "moth"
    / "scripts"
    / "make_activation_receipts.py"
)


def _inspection(state: str = "DISCOVERED") -> dict:
    return {
        "orchestration": {
            "decision_context": {
                "run_id": "run-001",
                "ordered_guidance_sources": ["mio", "architect-controller"],
            },
            "guidance": {
                "sources": [
                    {
                        "id": "mio",
                        "state": state,
                        "source_digest": "sha256:mio",
                    },
                    {
                        "id": "architect-controller",
                        "state": "DISCOVERED",
                        "source_digest": "sha256:architect",
                    },
                ]
            },
        }
    }


def test_plugin_receipt_helper_attests_only_ordered_discovered_sources(
    tmp_path,
) -> None:
    inspection = tmp_path / "inspection.json"
    receipts = tmp_path / "receipts.json"
    inspection.write_text(json.dumps(_inspection()), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--inspection",
            str(inspection),
            "--output",
            str(receipts),
            "--loaded-source",
            "mio",
            "--loaded-source",
            "architect-controller",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(receipts.read_text(encoding="utf-8"))
    assert [item["source_id"] for item in payload] == [
        "mio",
        "architect-controller",
    ]
    assert all(item["run_id"] == "run-001" for item in payload)
    assert all(item["executor_id"] == "codex-moth-skill" for item in payload)
    assert all(
        item["contract_id"] == "moth-skill-self-attestation-v1"
        for item in payload
    )
    assert all(item["evidence_refs"] for item in payload)
    assert str(tmp_path) not in repr(payload)


def test_plugin_receipt_helper_rejects_missing_attestation_or_source(
    tmp_path,
) -> None:
    inspection = tmp_path / "inspection.json"
    inspection.write_text(json.dumps(_inspection()), encoding="utf-8")

    missing = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--inspection",
            str(inspection),
            "--output",
            str(tmp_path / "receipts.json"),
            "--loaded-source",
            "mio",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert missing.returncode != 0
    assert "exactly match activation order" in missing.stderr

    inspection.write_text(
        json.dumps(_inspection(state="UNAVAILABLE")),
        encoding="utf-8",
    )
    unavailable = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--inspection",
            str(inspection),
            "--output",
            str(tmp_path / "receipts.json"),
            "--loaded-source",
            "mio",
            "--loaded-source",
            "architect-controller",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert unavailable.returncode != 0
    assert "not DISCOVERED" in unavailable.stderr
