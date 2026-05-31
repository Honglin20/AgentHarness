"""A tiny library with intentional call relationships, for codegraph demos.

Call graph (so demos have predictable answers):

    main → run_pipeline → load_data
                       → process
                            → normalize
                            → validate
                       → save_results
"""


def load_data(path: str) -> list[dict]:
    """Read JSON-like records from a file."""
    return [{"id": i, "raw": i * 2} for i in range(5)]


def normalize(record: dict) -> dict:
    """Clamp raw values into [0, 10]."""
    record["raw"] = max(0, min(10, record["raw"]))
    return record


def validate(record: dict) -> bool:
    """Reject records missing the id field."""
    return "id" in record and isinstance(record["id"], int)


def process(records: list[dict]) -> list[dict]:
    """Normalize and filter records."""
    out = []
    for r in records:
        r = normalize(r)
        if validate(r):
            out.append(r)
    return out


def save_results(records: list[dict], path: str) -> int:
    """Pretend to write records, return count."""
    return len(records)


def run_pipeline(in_path: str, out_path: str) -> int:
    """End-to-end ingest pipeline."""
    data = load_data(in_path)
    cleaned = process(data)
    return save_results(cleaned, out_path)


def main() -> int:
    return run_pipeline("input.json", "output.json")


if __name__ == "__main__":
    print(main())
