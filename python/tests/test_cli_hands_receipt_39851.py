"""#39851: `alterlab hands receipt show|verify` read /audit/export?include=receipts."""

from alterlab import cli, cli_hands

ROWS = [
    {"id": "r1", "task_id": "t1", "verdict": "confirmed", "signature_valid": True},
    {"id": "r2", "task_id": "t2", "verdict": "failed", "signature_valid": False},
]


class _Client:
    def __init__(self):
        self.calls = []

    def hands_request(self, method, path, body=None):
        self.calls.append((method, path))
        return {"audit": [], "receipts": ROWS}


def _run(*argv):
    args = cli.build_parser().parse_args(["hands", "receipt", *argv])
    client = _Client()
    return cli_hands.run(args, client), client


def test_show_reads_export_with_receipts_and_filters(capsys):
    code, client = _run("show", "--task", "t1")
    assert code == 0
    assert client.calls == [("GET", "/audit/export?include=receipts&format=json")]
    out = capsys.readouterr().out
    assert "r1" in out and "r2" not in out


def test_verify_fails_on_invalid_signature(capsys):
    code, _ = _run("verify")
    assert code == 1
    assert '"signature_valid":false' in capsys.readouterr().out


def test_verify_passes_for_valid_receipt_and_fails_when_none_match():
    assert _run("verify", "--id", "r1")[0] == 0
    assert _run("verify", "--id", "nope")[0] == 1
