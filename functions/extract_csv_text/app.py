import csv
import io
from typing import Any

from app_common.exceptions import DocumentExtractionError
from app_common.logging import get_logger, log_json
from app_common.s3_utils import get_object_bytes, put_text


logger = get_logger(__name__)


def _decode_csv(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise DocumentExtractionError("CSV document could not be decoded")


def _sniff_dialect(text: str) -> csv.Dialect:
    sample = text[:8192]
    try:
        return csv.Sniffer().sniff(sample)
    except csv.Error:
        return csv.excel


def _cell_to_str(value: str | None) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _rows_to_text(rows: list[list[str]]) -> str:
    return "\n".join("| " + " | ".join(_cell_to_str(cell) for cell in row) + " |" for row in rows)


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    bucket = event["document"]["bucket"]
    key = event["document"]["key"]
    output_bucket = event["artifacts"]["output_bucket"]
    output_prefix = event["artifacts"]["output_prefix"]

    csv_bytes = get_object_bytes(bucket, key)
    csv_text = _decode_csv(csv_bytes)
    dialect = _sniff_dialect(csv_text)

    reader = csv.reader(io.StringIO(csv_text), dialect)
    rows = [[_cell_to_str(cell) for cell in row] for row in reader]
    rows = [row for row in rows if any(cell for cell in row)]

    if not rows:
        raise DocumentExtractionError("CSV document is empty - no rows contain data")

    document_text = f"=== CSV: {key} ===\n{_rows_to_text(rows)}"
    raw_text_key = f"{output_prefix}/raw_text.txt"
    put_text(output_bucket, raw_text_key, document_text)

    max_columns = max(len(row) for row in rows)
    event["artifacts"]["raw_text"] = {
        "bucket": output_bucket,
        "key": raw_text_key,
    }
    event["csv_extraction"] = {
        "engine": "python-csv",
        "row_count": len(rows),
        "column_count": max_columns,
        "delimiter": dialect.delimiter,
        "text_length": len(document_text),
    }

    log_json(
        logger,
        "CSV text extracted",
        request_id=event["request_id"],
        row_count=len(rows),
        column_count=max_columns,
        text_length=len(document_text),
    )
    return event
