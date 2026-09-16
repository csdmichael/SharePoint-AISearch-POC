"""Fetch a bounded, source-attributed profile of the Databricks semiconductor data."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from azure.ai.projects import AIProjectClient
from azure.identity import AzureCliCredential, AzurePowerShellCredential, ChainedTokenCredential

try:
    from .deployment_config import (
        DEFAULT_CONFIG_PATH,
        foundry_project_endpoint,
        get_config_value,
        load_deployment_config,
        resolve_deployment_path,
    )
except ImportError:
    from deployment_config import (
        DEFAULT_CONFIG_PATH,
        foundry_project_endpoint,
        get_config_value,
        load_deployment_config,
        resolve_deployment_path,
    )


PII_COLUMN_PATTERN = re.compile(
    r"(^|_)(email|phone|mobile|ssn|social_security|passport|driver_license|date_of_birth|dob)(_|$)",
    re.IGNORECASE,
)
MUTATING_SQL_PATTERN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|merge|truncate|grant|revoke|call|execute)\b",
    re.IGNORECASE,
)
READ_ONLY_SQL_PREFIX = re.compile(r"^\s*(select|with|show|describe|desc|explain)\b", re.IGNORECASE)
TABLE_NAME_PATTERN = re.compile(r"^[A-Za-z_][\w-]*(\.[A-Za-z_][\w-]*){2,}$")


def source_table_names(profile: dict) -> list[str]:
    names = []
    for table in profile["source_tables"]:
        if isinstance(table, str):
            names.append(table)
        elif isinstance(table, dict):
            name = table.get("fully_qualified_table_name") or table.get("table_name")
            if name:
                names.append(name)
    return names


def column_tables(profile: dict) -> dict[str, list[dict]]:
    root = profile["column_definitions"]
    tables = root.get("tables", root) if isinstance(root, dict) else {}
    return {name: columns for name, columns in tables.items() if isinstance(columns, list)}


def representative_rows(profile: dict) -> list[dict]:
    samples = profile["representative_rows"]
    if isinstance(samples, dict) and isinstance(samples.get("rows"), list):
        return samples["rows"]
    rows = []
    for table_name, sample in samples.items():
        if not isinstance(sample, dict):
            continue
        for row in sample.get("rows", []):
            rows.append({"source_table": table_name, **row})
    return rows


def aggregate_tables(profile: dict) -> dict[str, dict]:
    root = profile["aggregate_metrics"]
    if isinstance(root, dict) and isinstance(root.get("results"), list):
        return {
            result["source_table"]: result
            for result in root["results"]
            if isinstance(result, dict) and result.get("source_table")
        }
    return {
        table_name: entry.get("values", entry)
        for table_name, entry in root.items()
        if isinstance(entry, dict) and table_name != "sql"
    }


def find_sql_values(value: Any) -> list[str]:
    sql_values = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower().endswith("sql") and isinstance(child, str):
                sql_values.append(child)
            else:
                sql_values.extend(find_sql_values(child))
    elif isinstance(value, list):
        for child in value:
            sql_values.extend(find_sql_values(child))
    return sql_values


def validate_profile(profile: dict) -> None:
    try:
        generated_at = datetime.fromisoformat(profile["generated_at"].replace("Z", "+00:00"))
    except (TypeError, ValueError) as error:
        raise ValueError("generated_at must be an ISO 8601 timestamp") from error
    if generated_at.utcoffset() is None:
        raise ValueError("generated_at must include a timezone offset")

    source_tables = source_table_names(profile)
    if len(source_tables) != len(set(source_tables)) or not source_tables:
        raise ValueError("source_tables must contain unique table names")
    unqualified_tables = [table for table in source_tables if not TABLE_NAME_PATTERN.fullmatch(table)]
    if unqualified_tables:
        raise ValueError(f"source_tables must be catalog.schema.table names: {unqualified_tables}")
    schemas = column_tables(profile)
    aggregates = aggregate_tables(profile)
    rows = representative_rows(profile)
    if not 1 <= len(rows) <= 100:
        raise ValueError(f"Representative sample must contain 1-100 rows, found {len(rows)}")

    missing_schemas = [table for table in source_tables if table not in schemas]
    missing_aggregates = [table for table in source_tables if table not in aggregates]
    if missing_schemas or missing_aggregates:
        raise ValueError(
            f"Profile coverage is incomplete; missing schemas={missing_schemas}, "
            f"missing aggregates={missing_aggregates}"
        )

    schema_fields = {}
    for table_name, columns in schemas.items():
        names = [column.get("column_name", column.get("name")) for column in columns]
        types = [column.get("data_type", column.get("type")) for column in columns]
        if not names or None in names or len(names) != len(set(names)):
            raise ValueError(f"Schema for {table_name} has missing or duplicate columns")
        if any(not isinstance(data_type, str) or not data_type.strip() for data_type in types):
            raise ValueError(f"Schema for {table_name} has missing column types")
        pii_columns = [name for name in names if PII_COLUMN_PATTERN.search(name)]
        if pii_columns:
            raise ValueError(f"Schema for {table_name} contains PII-like columns: {pii_columns}")
        schema_fields[table_name] = set(names)

    for table_name, aggregate in aggregates.items():
        row_count = aggregate.get("row_count")
        if not isinstance(row_count, int) or row_count < 0:
            raise ValueError(f"Aggregate for {table_name} has an invalid row_count")

    for row in rows:
        table_name = row.get("source_table")
        if table_name not in schema_fields:
            raise ValueError(f"Representative row references unknown table {table_name}")
        unexpected = set(row).difference(schema_fields[table_name], {"source_table"})
        if unexpected:
            raise ValueError(f"Representative row for {table_name} has unknown fields: {sorted(unexpected)}")

    sql_values = find_sql_values(profile)
    if not sql_values:
        raise ValueError("Profile must include source SQL attribution")
    mutating_statements = [sql for sql in sql_values if MUTATING_SQL_PATTERN.search(sql)]
    if mutating_statements:
        raise ValueError("Profile includes a mutating SQL statement")
    non_read_only_statements = [sql for sql in sql_values if not READ_ONLY_SQL_PREFIX.search(sql)]
    if non_read_only_statements:
        raise ValueError("Profile includes SQL outside the read-only allowlist")
    if not isinstance(profile["data_quality_notes"], list) or not profile["data_quality_notes"] or not all(
        isinstance(note, str) and note.strip() for note in profile["data_quality_notes"]
    ):
        raise ValueError("data_quality_notes must be a non-empty string list")


def parse_json_response(text: str) -> dict:
    """Parse a JSON response, tolerating a single Markdown JSON fence."""
    candidate = text.strip()
    if candidate.startswith("```"):
        first_newline = candidate.find("\n")
        candidate = candidate[first_newline + 1 :]
        if candidate.endswith("```"):
            candidate = candidate[:-3]
    profile = json.loads(candidate.strip())
    required = {
        "generated_at",
        "source_tables",
        "column_definitions",
        "aggregate_metrics",
        "representative_rows",
        "data_quality_notes",
    }
    missing = required.difference(profile)
    if missing:
        raise ValueError(f"Profile is missing required keys: {sorted(missing)}")
    if not profile["source_tables"] or not profile["representative_rows"]:
        raise ValueError("Profile contains no source tables or representative rows")
    validate_profile(profile)
    return profile


def fetch_profile(project_endpoint: str, agent_name: str, prompt: str) -> dict:
    project = AIProjectClient(
        endpoint=project_endpoint,
        credential=ChainedTokenCredential(
            AzurePowerShellCredential(),
            AzureCliCredential(),
        ),
    )
    openai_client = project.get_openai_client(agent_name=agent_name)
    conversation = openai_client.conversations.create()
    response = openai_client.responses.create(
        conversation=conversation.id,
        input=prompt,
    )
    return parse_json_response(response.output_text)


def representative_row_count(profile: dict) -> int:
    return len(representative_rows(profile))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch a semiconductor data profile through the existing Foundry agent."
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--project-endpoint")
    parser.add_argument("--agent-name")
    parser.add_argument(
        "--validate-existing",
        type=Path,
        help="Validate an existing profile without invoking the Foundry agent.",
    )
    parser.add_argument(
        "--output",
        type=Path,
    )
    args = parser.parse_args()
    config, _ = load_deployment_config(args.config)
    profile_source = get_config_value(config, "foundry", "profileSource")
    project_endpoint = args.project_endpoint or foundry_project_endpoint(
        get_config_value(profile_source, "accountName"),
        get_config_value(profile_source, "projectName"),
    )
    agent_name = args.agent_name or get_config_value(profile_source, "agentName")
    output_path = args.output or resolve_deployment_path(
        get_config_value(config, "paths", "profile")
    )
    prompt_path = resolve_deployment_path(get_config_value(profile_source, "promptPath"))
    prompt = prompt_path.read_text(encoding="utf-8").strip()
    if not prompt:
        parser.error(f"Profile prompt is empty: {prompt_path}")

    if args.validate_existing:
        profile = json.loads(args.validate_existing.read_text(encoding="utf-8"))
        validate_profile(profile)
        print(
            json.dumps(
                {
                    "input": str(args.validate_existing),
                    "source_tables": len(source_table_names(profile)),
                    "representative_rows": representative_row_count(profile),
                    "status": "passed",
                }
            )
        )
        return

    profile = fetch_profile(project_endpoint, agent_name, prompt)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(profile, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "source_tables": len(profile["source_tables"]),
                "representative_rows": representative_row_count(profile),
                "generated_at": profile["generated_at"],
            }
        )
    )


if __name__ == "__main__":
    main()