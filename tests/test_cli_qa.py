"""End-to-end CLI QA integration tests."""

import pytest
from typer.testing import CliRunner
from ff.cli import app
from ff.core.config import Config, save_config
from ff.sleeper import detect_format

runner = CliRunner()


def _write_config(league):
    save_config(Config(
        league_id="LG1", season="2026", name="Test Dynasty",
        format=detect_format(league), username="alice", user_id="userA",
    ))


def test_cli_qa_footer_in_summary_mode(fake_clients, league, monkeypatch):
    monkeypatch.setenv("FF_QA", "1")
    _write_config(league)

    result = runner.invoke(app, ["roster"])
    assert result.exit_code == 0, result.output
    assert "QA:" in result.output
    assert "checks passed" in result.output


def test_cli_qa_footer_in_verbose_mode(fake_clients, league, monkeypatch):
    monkeypatch.setenv("FF_QA", "verbose")
    _write_config(league)

    result = runner.invoke(app, ["power"])
    assert result.exit_code == 0, result.output
    assert "QA Inspection" in result.output
    assert "PASS" in result.output


def test_cli_qa_off_by_default(fake_clients, league, monkeypatch):
    monkeypatch.delenv("FF_QA", raising=False)
    _write_config(league)

    result = runner.invoke(app, ["roster"])
    assert result.exit_code == 0, result.output
    assert "QA:" not in result.output


def test_cli_ff_qa_command(fake_clients, league):
    _write_config(league)

    result = runner.invoke(app, ["qa"])
    assert result.exit_code == 0, result.output
    assert "QA Health Scorecard" in result.output
    assert "ALL INVARIANTS PASSED" in result.output


def test_cli_ff_qa_verbose_command(fake_clients, league):
    _write_config(league)

    result = runner.invoke(app, ["qa", "--verbose"])
    assert result.exit_code == 0, result.output
    assert "QA Health Scorecard" in result.output
    assert "QA Inspection" in result.output


def test_cli_qa_across_all_commands(fake_clients, league, monkeypatch):
    monkeypatch.setenv("FF_QA", "1")
    _write_config(league)

    commands = [
        ["values", "-p", "WR"],
        ["values", "--market", "dealer"],
        ["trade", "--give", "Ja'Marr Chase", "--get", "Bijan Robinson"],
        ["trade", "--give", "Ja'Marr Chase", "--get", "Bijan Robinson", "--market", "dealer"],
        ["picks"],
        ["cleanup"],
        ["waivers"],
        ["lineup", "--week", "1"],
        ["news"],
        ["movers", "--buy"],
        ["movers", "--arbitrage"],
        ["draft", "--draft-id", "DR1"],
    ]

    for cmd in commands:
        result = runner.invoke(app, cmd)
        assert result.exit_code == 0, f"Command {' '.join(cmd)} failed: {result.output}"
        assert "QA:" in result.output, f"Command {' '.join(cmd)} missing QA footer: {result.output}"
