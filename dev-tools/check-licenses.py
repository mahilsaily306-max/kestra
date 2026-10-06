#!/usr/bin/env python3
"""Fail when a dependency in a license report has no license or only offending licenses.

Usage:
    ./gradlew licenseReport
    python3 dev-tools/check-licenses.py [build/reports/licenses/licenseReport.json] [--sarif license-check.sarif]

    cd ui && npx license-compliance --report detailed --production --format json > /tmp/ui-licenses.json
    python3 dev-tools/check-licenses.py /tmp/ui-licenses.json

The report format is detected from its entries: Gradle lists the alternatives of a dual-licensed
library in `licenses`, npm gives one SPDX expression in `license`. A dependency is accepted as
soon as one alternative (SPDX `OR`) is acceptable, and rejected as soon as one member of an `AND` is not.

With `--sarif`, the findings are also written as a SARIF 2.1.0 file, which can be uploaded as code scanning results.
Dependencies accepted by exception are included as suppressed results.
"""
import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

DEFAULT_REPORT = Path(__file__).resolve().parent.parent / "build/reports/licenses/licenseReport.json"

# Licenses that are never acceptable on their own. A GPL variant with a linking exception
# (Classpath Exception, CPE, Universal FOSS Exception) is not matched here.
OFFENDING = re.compile(
    r"\b(a?gpl(?:v?\d|\b)|(?:general public license|sspl|server side public|busl|business source|commons clause|"
    r"cc[- ]by[- ]nc|non[- ]?commercial|proprietary|unlicensed)\b)",
    re.IGNORECASE,
)
LINKING_EXCEPTION = re.compile(r"\b(cpe|classpath[- ]exception|universal foss exception)\b", re.IGNORECASE)
NO_LICENSE = re.compile(r"(unknown|no license found|none|see license.*)?", re.IGNORECASE)

SARIF_RULES = {
    "missing-license": ("Dependency without a license", "The dependency does not declare any license."),
    "offending-license": ("Dependency with an offending license", "The dependency is only available under a license that is not acceptable."),
}
MANIFESTS = {"gradle": "build.gradle", "npm": "ui/package.json"}

# Dependencies (Gradle group:artifact, npm name) reviewed by hand and accepted despite a missing or offending license.
ALLOWED_DEPENDENCIES: set[str] = {
    "@kestra-io/design-system",
    "@kestra-io/slot-contracts",
    "@kestra-io/topology",
    "jsonify",  # Public Domain according to its package.json
    "khroma",  # MIT according to its license file
}


def split_expression(expression: str, operator: str) -> list[str]:
    """Split an SPDX expression on a top-level operator, ignoring the ones inside parentheses."""
    parts, depth, start = [], 0, 0
    for match in re.finditer(r"[()]|\s+" + operator + r"\s+", expression, re.IGNORECASE):
        if match.group() == "(":
            depth += 1
        elif match.group() == ")":
            depth -= 1
        elif depth == 0:
            parts.append(expression[start:match.start()])
            start = match.end()
    return [*parts, expression[start:]]


def unwrap(expression: str) -> str:
    """Strip the parentheses wrapping the whole expression, as in `(MIT OR Apache-2.0)`."""
    expression = expression.strip()
    while expression.startswith("(") and expression.endswith(")"):
        depth = 0
        for char in expression[:-1]:
            depth += (char == "(") - (char == ")")
            if depth == 0:
                return expression
        expression = expression[1:-1].strip()
    return expression


def is_offending(license_name: str) -> bool:
    license_name = unwrap(license_name)
    alternatives = split_expression(license_name, "OR")
    if len(alternatives) > 1:
        return all(is_offending(alternative) for alternative in alternatives)
    members = split_expression(license_name, "AND")
    if len(members) > 1:
        return any(is_offending(member) for member in members)
    if LINKING_EXCEPTION.search(license_name):
        return False
    # LGPL is a weak copyleft, acceptable for a dynamically linked library.
    if re.search(r"\blgpl\b|(?:lesser|library) general public", license_name, re.IGNORECASE):
        return False
    return bool(OFFENDING.search(license_name))


def sarif_result(rule_id: str, dependency: str, licenses: str, manifest: str, suppressed: bool) -> dict:
    result = {
        "ruleId": rule_id,
        "level": "error",
        "message": {"text": f"{dependency}: {licenses}" if rule_id == "offending-license" else f"{dependency} has no license."},
        "locations": [{"physicalLocation": {"artifactLocation": {"uri": manifest, "uriBaseId": "%SRCROOT%"}, "region": {"startLine": 1}}}],
        "partialFingerprints": {"licenseCheck/v1": f"{rule_id}:{dependency}"},
    }
    if suppressed:
        result["suppressions"] = [{"kind": "inSource", "status": "accepted", "justification": "Listed in ALLOWED_DEPENDENCIES of dev-tools/check-licenses.py."}]
    return result


def write_sarif(path: Path, results: list[dict]) -> None:
    rules = [
        {"id": rule_id, "name": rule_id, "defaultConfiguration": {"level": "error"}, "shortDescription": {"text": title}, "fullDescription": {"text": description}}
        for rule_id, (title, description) in SARIF_RULES.items()
    ]
    sarif = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [{"tool": {"driver": {"name": "kestra-license-check", "rules": rules}}, "results": results}],
    }
    path.write_text(json.dumps(sarif, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Check a license report for missing or offending licenses.")
    parser.add_argument("report", nargs="?", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--sarif", type=Path, help="also write the findings to this SARIF file")
    args = parser.parse_args()
    report = args.report
    if not report.is_file():
        print(f"License report '{report}' not found, run './gradlew licenseReport' first.", file=sys.stderr)
        return 2

    missing, offending, accepted = [], [], []
    sarif_results: dict[tuple[str, str], dict] = {}
    manifest = MANIFESTS["gradle"]
    license_counts: Counter[str] = Counter()
    with report.open(encoding="utf-8") as file:
        for row in json.load(file):
            manifest = MANIFESTS["gradle" if "licenses" in row else "npm"]
            if "licenses" in row:
                dependency = row["dependency"]
                licenses = [(entry.get("license") or "").strip() for entry in row["licenses"]]
            else:
                dependency = "{}@{}".format(row["name"], row["version"])
                licenses = [(row.get("license") or "").strip()]
            license_counts.update(name or "(none)" for name in licenses or [""])
            if all(NO_LICENSE.fullmatch(name) for name in licenses):
                problem, rule_id = missing, "missing-license"
            elif all(NO_LICENSE.fullmatch(name) or is_offending(name) for name in licenses):
                problem, rule_id = offending, "offending-license"
            else:
                continue
            is_accepted = ":".join(dependency.split(":")[:2]) in ALLOWED_DEPENDENCIES or row.get("name") in ALLOWED_DEPENDENCIES
            license_names = ", ".join(name or "(none)" for name in licenses)
            (accepted if is_accepted else problem).append((dependency, license_names))
            sarif_results[(rule_id, dependency)] = sarif_result(rule_id, dependency, license_names, manifest, is_accepted)

    print("Dependencies per license (a dual-licensed dependency counts once per license):")
    for name, count in sorted(license_counts.items(), key=lambda item: (-item[1], item[0])):
        print(f"  {count:4d}  {name}")
    print()

    if accepted:
        print("Dependencies accepted by exception (ALLOWED_DEPENDENCIES) despite a missing or offending license:")
        for dependency, licenses in sorted(accepted):
            print(f"  {dependency}: {licenses}")
    if missing:
        print("Dependencies without a license:")
        for dependency, _ in sorted(missing):
            print(f"  {dependency}")
    if offending:
        print("Dependencies with an offending license:")
        for dependency, licenses in sorted(offending):
            print(f"  {dependency}: {licenses}")
    if not missing and not offending:
        print("No dependency without a license or with an offending license, apart from the exceptions above." if accepted else "No dependency without a license or with an offending license.")
    if args.sarif:
        write_sarif(args.sarif, list(sarif_results.values()))
        print(f"SARIF report written to '{args.sarif}'.")
    return 1 if missing or offending else 0


if __name__ == "__main__":
    sys.exit(main())
