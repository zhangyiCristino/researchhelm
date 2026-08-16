from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from sanitize_export import scan_value  # noqa: E402
from validate_state import load_json, load_run, validate_loaded  # noqa: E402


TEMPLATE = SCRIPT_DIR.parent / "assets" / "templates" / "research-cockpit.html"
PUBLIC_REPORT_KEYS = {
    "schema_version",
    "source_kind",
    "files_exported",
    "artifacts_exported",
    "records_exported",
    "public_fields_retained",
    "project_private_fields_removed",
    "finding_count",
    "findings",
}


class CockpitError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class UsageError(ValueError):
    pass


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise UsageError(message)


def collect_run(loaded: dict[str, Any]) -> dict[str, Any]:
    return {
        "brief": loaded["research-brief.json"],
        "evidence": loaded["evidence.jsonl"],
        "ideas": loaded["idea-candidates.json"],
        "decisions": loaded["decision-log.jsonl"],
        "skill_recommendations": loaded["skill-recommendations.jsonl"],
        "experiments": loaded["experiment-ledger.jsonl"],
        "artifacts": loaded["artifact-manifest.json"],
        "claims": loaded["claim-evidence.json"],
    }


def script_safe_json(value: Any) -> str:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        .replace("</", "<\\/")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def _records(data: dict[str, Any]):
    for value in data.values():
        yield from value if isinstance(value, list) else [value]


def _remove_public_audit_metadata(data: dict[str, Any]) -> None:
    for record in _records(data):
        if isinstance(record, dict):
            record.pop("field_sensitivity", None)


def _scan_collected(data: dict[str, Any]) -> bool:
    try:
        for record in _records(data):
            if scan_value(record):
                return True
    except Exception:
        return True
    return False


def _classification_summary(
    data: dict[str, Any],
) -> tuple[int, int, bool] | None:
    records = 0
    public_fields = 0
    has_project_private = False
    for record in _records(data):
        records += 1
        if not isinstance(record, dict):
            return None
        sensitivity = record.get("field_sensitivity")
        if not isinstance(sensitivity, dict):
            return None
        for classification in sensitivity.values():
            if classification == "public":
                public_fields += 1
            elif classification == "project-private":
                has_project_private = True
            else:
                return None
    return records, public_fields, has_project_private


def _is_nonnegative_int(value: object) -> bool:
    return type(value) is int and value >= 0


def _load_public_report(
    run_dir: Path, data: dict[str, Any]
) -> dict[str, Any]:
    report_path = run_dir / "sanitization-report.json"
    try:
        report = load_json(report_path)
    except (OSError, UnicodeError, ValueError) as error:
        raise CockpitError("ERR_PUBLIC_EXPORT_REQUIRED") from error
    summary = _classification_summary(data)
    if not isinstance(report, dict) or summary is None:
        raise CockpitError("ERR_PUBLIC_EXPORT_REQUIRED")
    records, public_fields, _has_project_private = summary
    artifacts_exported = report.get("artifacts_exported")
    if (
        set(report) != PUBLIC_REPORT_KEYS
        or report.get("schema_version") != "1.0"
        or report.get("source_kind") != "sanitized-public-export"
        or not _is_nonnegative_int(artifacts_exported)
        or report.get("files_exported") != len(data) + artifacts_exported
        or report.get("records_exported") != records
        or report.get("public_fields_retained") != public_fields
        or not _is_nonnegative_int(
            report.get("project_private_fields_removed")
        )
        or not _is_nonnegative_int(report.get("finding_count"))
        or report.get("finding_count") != 0
        or report.get("findings") != []
    ):
        raise CockpitError("ERR_PUBLIC_EXPORT_REQUIRED")
    return report


def _public_export_is_unsafe(data: dict[str, Any]) -> bool:
    summary = _classification_summary(data)
    return (
        summary is None
        or summary[2]
        or _scan_collected(data)
    )


def _atomic_write(output: Path, html: str) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="\n",
            delete=False,
            dir=output.parent,
            prefix=f".{output.name}.",
            suffix=".tmp",
        ) as handle:
            handle.write(html)
            temporary = Path(handle.name)
        os.replace(temporary, output)
    except Exception:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise


def render_cockpit(
    run_dir: Path, output: Path, public: bool = False
) -> Path:
    run_dir = Path(run_dir)
    output = Path(output)
    loaded, parsing_findings = load_run(run_dir)
    errors = [
        item
        for item in validate_loaded(run_dir, loaded, parsing_findings)
        if item.severity == "error"
    ]
    if errors:
        raise CockpitError("ERR_INVALID_STATE")

    data = collect_run(loaded)
    if public:
        _load_public_report(run_dir, data)
        if _public_export_is_unsafe(data):
            raise CockpitError("ERR_UNSAFE_STATE")
        _remove_public_audit_metadata(data)

    template = TEMPLATE.read_text(encoding="utf-8")
    if template.count("__RESEARCHHELM_DATA__") != 1:
        raise CockpitError("ERR_TEMPLATE_INVALID")
    data["data_boundary"] = (
        "Public sanitized export"
        if public
        else "Private local Cockpit - do not commit"
    )
    html = template.replace("__RESEARCHHELM_DATA__", script_safe_json(data))
    _atomic_write(output, html)
    return output


def main(argv: list[str] | None = None) -> int:
    parser = SafeArgumentParser(add_help=True)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--public", action="store_true")
    try:
        args = parser.parse_args(argv)
        output = args.output or args.run_dir / "research-cockpit.html"
        rendered = render_cockpit(args.run_dir, output, public=args.public)
        print(rendered)
        return 0
    except UsageError:
        print("ERR_USAGE", file=sys.stderr)
        return 2
    except CockpitError as error:
        print(error.code, file=sys.stderr)
        return 1
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        print("ERR_IO", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
