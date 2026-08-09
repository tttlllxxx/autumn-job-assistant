from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models.entities import Application
from app.services.applications_csv import CSV_HEADERS, export_csv, parse_csv


def test_csv_round_trip_preserves_all_values_and_column_order() -> None:
    source = (
        "\ufeff" + ",".join(CSV_HEADERS) + "\n"
        "虚构科技,官网,RAG工程师,校招,AI平台,https://example.invalid/job,北京,2026/08/01,已投递,投递,待处理,2026-08-01 09:30,CODE-X,虚构联系人,,待定,包含逗号的备注需加引号\n"
    )
    # Use csv writer-compatible quoting for the last field in a realistic row.
    source = source.replace("包含逗号的备注需加引号", '"包含,逗号的备注"')
    rows, errors = parse_csv(source.encode("utf-8"))
    assert errors == []
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        application = Application(**rows[0])
        db.add(application)
        db.commit()
        output = export_csv([application])
    parsed_again, errors_again = parse_csv(output.encode("utf-8"))
    assert errors_again == []
    assert parsed_again[0]["raw_values"] == rows[0]["raw_values"]
    assert output.lstrip("\ufeff").splitlines()[0] == ",".join(CSV_HEADERS)


def test_csv_invalid_enum_is_preview_error_and_no_rows_are_returned() -> None:
    values = [""] * len(CSV_HEADERS)
    values[0] = "虚构公司"
    values[8] = "不存在的状态"
    content = (",".join(CSV_HEADERS) + "\n" + ",".join(values) + "\n").encode()
    rows, errors = parse_csv(content)
    assert rows == []
    assert errors[0]["row"] == 2
    assert errors[0]["errors"][0]["column"] == "状态"


def test_csv_rejects_wrong_header_order() -> None:
    content = (",".join(reversed(CSV_HEADERS)) + "\n").encode()
    try:
        parse_csv(content)
    except ValueError as exc:
        assert "表头或列顺序" in str(exc)
    else:
        raise AssertionError("wrong header order must fail")
