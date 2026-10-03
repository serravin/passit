"""Security findings must be visible without echoing matched secrets into CI logs."""

import importlib.util
import json
import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "scan_report.py"
SPEC = importlib.util.spec_from_file_location("scan_report", SCRIPT)
scan_report = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scan_report)


def test_findings_show_fix_versions_without_exposing_matched_secrets():
    report = {
        "Results": [
            {
                "Target": "test-image",
                "Vulnerabilities": [
                    {
                        "VulnerabilityID": "CVE-TEST-1",
                        "PkgName": "example",
                        "Severity": "CRITICAL",
                        "InstalledVersion": "1.0",
                        "FixedVersion": "1.1",
                    },
                    {"VulnerabilityID": "CVE-TEST-2", "PkgName": "other", "Severity": "HIGH"},
                    {"VulnerabilityID": "CVE-LOW", "PkgName": "low", "Severity": "LOW"},
                ],
                "Secrets": [
                    {
                        "RuleID": "api-key",
                        "Title": "API key",
                        "Severity": "HIGH",
                        "Match": "PRIVATE_SECRET",
                        "Code": {"Lines": [{"Content": "PRIVATE_SECRET"}]},
                    }
                ],
                "Misconfigurations": [
                    {
                        "ID": "CONFIG-1",
                        "Title": "Unsafe configuration",
                        "Severity": "HIGH",
                        "CauseMetadata": {"Code": "PRIVATE_SECRET"},
                    }
                ],
            }
        ],
    }
    text = scan_report.render(report, "report.json")
    assert "findings: **4**" in text
    assert "CVE-TEST-1 | example | 1.0 | 1.1" in text
    assert "No fix listed" in text
    assert "api-key" in text and "CONFIG-1" in text
    assert "PRIVATE_SECRET" not in text and "CVE-LOW" not in text


def test_cli_writes_the_same_readable_report_to_logs_and_summary(tmp_path):
    report = tmp_path / "report.json"
    summary = tmp_path / "summary.md"
    report.write_text(json.dumps({"Results": []}))
    env = {**os.environ, "GITHUB_STEP_SUMMARY": str(summary)}
    result = subprocess.run(["python", str(SCRIPT), str(report)], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "No HIGH/CRITICAL findings" in result.stdout
    assert summary.read_text().strip() == result.stdout.strip()


def test_missing_report_is_not_reported_as_a_clean_scan(tmp_path):
    env = dict(os.environ)
    env.pop("GITHUB_STEP_SUMMARY", None)
    result = subprocess.run(
        ["python", str(SCRIPT), str(tmp_path / "missing.json")], env=env, capture_output=True, text=True
    )
    assert result.returncode == 1
    assert "missing or invalid" in result.stdout
    assert "No HIGH/CRITICAL findings" not in result.stdout
