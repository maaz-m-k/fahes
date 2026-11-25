"""The judges' offline command, run as a real process."""
import csv
import json
import subprocess
import sys


def run(args, cwd):
    return subprocess.run([sys.executable, "-m", "istibaq", *args], cwd=cwd, capture_output=True, text=True,
                          check=True, timeout=120)


def test_plain_list_to_csv(tmp_path):
    src = tmp_path / "links.txt"
    src.write_text("https://www.adpolice.gov.ae/\ntamm-pay.test\nhttps://bit.ly/abc\n\ngoogle.com\n", encoding="utf-8")
    out = tmp_path / "out.csv"
    run(["score", str(src), "--out", str(out)], tmp_path)
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    assert [r["link"] for r in rows] == ["https://www.adpolice.gov.ae/", "tamm-pay.test", "https://bit.ly/abc", "google.com"]
    assert list(rows[0].keys()) == ["link", "is_fraud", "score", "verdict", "reasons", "model_version", "scored_at"]
    by = {r["link"]: r for r in rows}
    assert by["https://www.adpolice.gov.ae/"]["verdict"] == "green"
    assert by["tamm-pay.test"]["is_fraud"] == "yes" and by["tamm-pay.test"]["verdict"] == "red"
    assert by["https://bit.ly/abc"]["verdict"] == "grey"
    assert by["google.com"]["is_fraud"] == "no"


def test_csv_with_url_column_and_jsonl(tmp_path):
    src = tmp_path / "links.csv"
    src.write_text("id,url\n1,tamm.abudhabi\n2,adpolice-fines.example\n", encoding="utf-8")
    out = tmp_path / "out.jsonl"
    run(["score", str(src), "--mode", "officer", "--format", "jsonl", "--out", str(out)], tmp_path)
    rows = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines()]
    assert [r["link"] for r in rows] == ["tamm.abudhabi", "adpolice-fines.example"]
    assert rows[0]["verdict"] == "green"
    assert rows[1]["verdict"] == "red" and rows[1]["is_fraud"] is True
    assert rows[1]["reasons"][0]["ar"]


def test_stdout_when_no_out(tmp_path):
    src = tmp_path / "links.txt"
    src.write_text("tamm-pay.test\n", encoding="utf-8")
    res = run(["score", str(src)], tmp_path)
    assert res.stdout.splitlines()[0].startswith("link,is_fraud,score,verdict")


def test_online_flag_follows_short_links(tmp_path, monkeypatch, capsys):
    from istibaq import cli
    from istibaq.core.contract import OnlineFacts
    seen = []

    def fake(link):
        seen.append(link)
        return OnlineFacts(redirect_chain=[link, "https://tamm-pay.example/login"])
    monkeypatch.setattr(cli, "_online_facts", fake)
    f = tmp_path / "links.txt"
    f.write_text("https://bit.ly/fine\n")
    assert cli.main(["score", str(f), "--online"]) == 0
    out = capsys.readouterr().out
    assert seen == ["https://bit.ly/fine"] and ",yes," in out
