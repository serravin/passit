"""Show Trivy findings in CI logs and summaries without printing secret matches."""

import argparse
import json
import os
from pathlib import Path


def findings(report):
    rows = []
    for result in report.get("Results") or []:
        target = result.get("Target", "unknown")
        for item in result.get("Vulnerabilities") or []:
            if item.get("Severity") in {"HIGH", "CRITICAL"}:
                rows.append(
                    (
                        target,
                        "Vulnerability",
                        item["Severity"],
                        item.get("VulnerabilityID", ""),
                        item.get("PkgName", ""),
                        item.get("InstalledVersion", ""),
                        item.get("FixedVersion") or "No fix listed",
                    )
                )
        for kind in ("Secrets", "Misconfigurations"):
            for item in result.get(kind) or []:
                if item.get("Severity") in {"HIGH", "CRITICAL"}:
                    # Never include Match, Code, CauseMetadata or raw configuration values.
                    rows.append(
                        (
                            target,
                            kind,
                            item["Severity"],
                            item.get("RuleID") or item.get("ID", ""),
                            item.get("Title", ""),
                            "",
                            "",
                        )
                    )
    return rows


def cell(value):
    return str(value).replace("\\", "\\\\").replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def render(report, label):
    rows = findings(report)
    text = f"### Trivy: {cell(label)}\n\n"
    text += f"HIGH/CRITICAL findings: **{len(rows)}**\n\n"
    if rows:
        text += "| Target | Type | Severity | ID | Package / rule | Installed | Fixed |\n"
        text += "|---|---|---|---|---|---|---|\n"
        for row in rows[:200]:
            text += "| " + " | ".join(cell(value) for value in row) + " |\n"
        if len(rows) > 200:
            text += "\nFirst 200 findings shown; download the JSON artifact for the complete report.\n"
    else:
        text += "No HIGH/CRITICAL findings in this report.\n"
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    try:
        text = render(json.loads(args.report.read_text()), args.report.name)
    except (OSError, ValueError, AttributeError, TypeError, KeyError):
        print("Trivy report missing or invalid; check the scanner step for its failure reason.")
        raise SystemExit(1) from None
    print(text)
    if path := os.getenv("GITHUB_STEP_SUMMARY"):
        with open(path, "a") as summary:
            summary.write(text)


if __name__ == "__main__":
    main()
