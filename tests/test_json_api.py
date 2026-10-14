from __future__ import annotations

import datetime
from decimal import Decimal
from difflib import Differ
from http import HTTPStatus
from importlib.metadata import version
from io import BytesIO
from pathlib import Path
from typing import Any
from typing import cast
from typing import TYPE_CHECKING

import pytest
from beancount.core import data
from msgspec.json import Decoder

from fava.beans.funcs import hash_entry
from fava.context import g
from fava.core import FilteredLedger
from fava.core.file import _sha256_str
from fava.core.file import get_entry_slice
from fava.core.misc import align
from fava.json_api import _sample_events
from fava.json_api import build_json_body_decoder
from fava.json_api import build_query_string_decoder
from fava.json_api import ProblemDetails
from fava.json_api import SuccessResponse
from fava.json_api import ValidationError

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Sequence

    from flask import Flask
    from flask.testing import FlaskClient
    from werkzeug.test import TestResponse

    from fava.beans.abc import Event
    from fava.core import FavaLedger

    from .conftest import GetFavaLedger
    from .conftest import SnapshotFunc


def diff_strings(a: str, b: str) -> list[str]:
    """Diff two strings and return the list of differing lines."""
    differ = Differ()
    return [
        line
        for line in differ.compare(a.splitlines(), b.splitlines())
        if line.startswith(("+", "-"))
    ]


def test_query_string_decoder_no_params() -> None:
    def noparams() -> None:
        pass

    assert build_query_string_decoder(noparams) is None


def test_query_string_decoder_str_and_int_params() -> None:
    def func(
        test: str, number: int, with_default: str = "asdf"
    ) -> tuple[str, int, str]:
        return test, number, with_default

    decoder = build_query_string_decoder(func)
    assert decoder
    with pytest.raises(ValidationError, match="missing required field `test`"):
        decoder({"notest": "value"})
    args = decoder({"test": "value", "number": "10"})
    assert isinstance(args, tuple)
    assert len(args) == 3
    assert isinstance(args[0], str)
    assert isinstance(args[1], int)
    assert isinstance(args[2], str)
    assert func(args[0], args[1], args[2]) == (
        "value",
        10,
        "asdf",
    )


def test_json_body_decoder() -> None:
    def func(test: str, items: list[int]) -> tuple[str, list[int]]:
        return test, items

    decoder = build_json_body_decoder(func)
    assert decoder
    with pytest.raises(ValidationError, match="Invalid JSON"):
        decoder(b"{{")
    with pytest.raises(ValidationError, match="missing required field `test`"):
        decoder(b"{}")
    args = decoder(b'{"test":"value","items":[1,2,3]}')
    assert isinstance(args, tuple)
    assert isinstance(args[0], str)
    assert isinstance(args[1], list)
    assert func(args[0], args[1]) == (
        "value",
        [1, 2, 3],
    )


_error_decoder = Decoder(ProblemDetails)
_success_decoder = Decoder(SuccessResponse)


def assert_api_error(
    response: TestResponse,
    msg: str | None = None,
    *,
    status: HTTPStatus = HTTPStatus.INTERNAL_SERVER_ERROR,
    title: str | None = None,
) -> str:
    """Asserts that the response errored and contains the message."""
    assert response.status_code == status.value
    assert response.content_type == "application/problem+json"
    json = _error_decoder.decode(response.data)
    assert json.status == status.value
    if title:
        assert title == json.title
    if msg:
        assert msg == json.detail
    return json.detail


def assert_api_success(
    response: TestResponse, data: object | None = None
) -> Any:  # noqa: ANN401 - API payloads are intentionally untyped JSON.
    """Asserts that the request was successful and contains the data."""
    assert response.status_code == HTTPStatus.OK.value
    json = _success_decoder.decode(response.data)
    assert json
    if data is not None:
        assert data == json.data
    return json.data


def test_api_changed(test_client: FlaskClient) -> None:
    response = test_client.get("/long-example/api/changed")
    assert_api_success(response, data=False)


def test_api_add_document_and_move_and_delete(
    app: Flask,
    test_client: FlaskClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    add_url = "/long-example/api/add_document"
    get_url = "/long-example/document/"
    move_url = "/long-example/api/move"
    delete_url = "/long-example/api/document"
    account = "Expenses:Food:Restaurant"
    account_dir = tmp_path / "Expenses" / "Food" / "Restaurant"

    def _data(
        filename: str,
    ) -> dict[str, str | tuple[BytesIO, str]]:
        return {
            "folder": str(tmp_path),
            "account": account,
            "file": (BytesIO(b"asdfasdf"), filename),
        }

    with app.test_request_context("/long-example/"):
        app.preprocess_request()

        # error when no documents dir is set
        monkeypatch.setitem(g.ledger.options, "documents", [])  # ty:ignore[invalid-argument-type]

        response = test_client.put(add_url)
        assert_api_error(
            response,
            "You need to set a documents folder.",
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
            title="DocumentDirectoryMissingError",
        )

        # upload to temporary directory
        monkeypatch.setitem(g.ledger.options, "documents", [str(tmp_path)])  # ty:ignore[invalid-argument-type]
        monkeypatch.setattr(
            g.ledger.fava_options, "import_dirs", [str(account_dir)]
        )

        response = test_client.put(add_url)
        assert_api_error(
            response, "No file uploaded.", status=HTTPStatus.BAD_REQUEST
        )

        response = test_client.put(add_url, data=_data(""))
        assert_api_error(
            response,
            "Uploaded file is missing filename.",
            status=HTTPStatus.BAD_REQUEST,
        )

        for missing in ("folder", "account"):
            data = _data("2015-12-12 test")
            del data[missing]
            response = test_client.put(add_url, data=data)
            assert_api_error(
                response,
                f"Invalid API request: Object missing"
                f" required field `{missing}`",
                status=HTTPStatus.BAD_REQUEST,
            )

        filename = account_dir / "2015-12-12 test"
        assert not filename.exists()
        response = test_client.put(add_url, data=_data("2015-12-12 test"))
        assert_api_success(response, f"Uploaded to {filename}")
        assert filename.read_text() == "asdfasdf"
        assert filename.is_file()

        response = test_client.get(
            get_url, query_string={"filename": str(filename)}
        )
        assert response.status_code == HTTPStatus.OK.value
        assert response.get_data() == b"asdfasdf"

        response = test_client.put(add_url, data=_data("2015-12-12 test"))
        assert_api_error(
            response, f"{filename} already exists.", status=HTTPStatus.CONFLICT
        )

        # move to same path should fail
        response = test_client.put(
            move_url,
            json={
                "account": account,
                "filename": str(filename),
                "new_name": "2015-12-12 test",
            },
        )
        assert_api_error(
            response, f"{filename} already exists.", status=HTTPStatus.CONFLICT
        )

        response = test_client.put(
            move_url,
            json={
                "account": account,
                "filename": str(filename),
                "new_name": "2015-12-12 test_moved",
            },
        )
        new_filename = account_dir / "2015-12-12 test_moved"
        assert_api_success(response, f"Moved {filename} to {new_filename}.")
        assert not filename.exists()
        assert new_filename.exists()

        # delete
        invalid_filename = tmp_path / "asdf"
        response = test_client.delete(
            delete_url,
            query_string={"filename": str(invalid_filename)},
        )
        assert_api_error(
            response,
            f"Not valid document or import file: '{invalid_filename}'.",
            status=HTTPStatus.BAD_REQUEST,
        )

        response = test_client.delete(
            delete_url,
            query_string={"filename": str(filename)},
        )
        assert_api_error(
            response,
            f"{filename} does not exist.",
            status=HTTPStatus.NOT_FOUND,
        )

        response = test_client.delete(
            delete_url,
            query_string={"filename": str(new_filename)},
        )
        assert_api_success(response, f"Deleted {new_filename}.")


def test_api_upload_import_file(
    app: Flask,
    test_client: FlaskClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = "/long-example/api/upload_import_file"

    with app.test_request_context("/long-example/"):
        app.preprocess_request()

        monkeypatch.setattr(
            g.ledger.fava_options, "import_dirs", [str(tmp_path)]
        )

        response = test_client.put(url)
        assert_api_error(
            response, "No file uploaded.", status=HTTPStatus.BAD_REQUEST
        )

        response = test_client.put(
            url, data={"file": (BytesIO(b"asdfasdf"), "")}
        )
        assert_api_error(
            response,
            "Uploaded file is missing filename.",
            status=HTTPStatus.BAD_REQUEST,
        )

        filename = tmp_path / "receipt.pdf"
        assert not filename.is_file()
        response = test_client.put(
            url, data={"file": (BytesIO(b"asdfasdf"), "receipt.pdf")}
        )
        assert_api_success(response, f"Uploaded to {filename}")
        assert filename.is_file()

        # Uploading the exact same file should fail due to path conflict
        response = test_client.put(
            url, data={"file": (BytesIO(b"asdfasdf"), "receipt.pdf")}
        )
        assert_api_error(
            response, f"{filename} already exists.", status=HTTPStatus.CONFLICT
        )


def test_api_errors(test_client: FlaskClient, snapshot: SnapshotFunc) -> None:
    response = test_client.get("/long-example/api/errors")
    assert_api_success(response, [])
    response = test_client.get("/errors/api/errors")
    data = assert_api_success(response)

    def get_message(err: dict[str, str]) -> str:
        return str(err["message"])

    assert isinstance(data, list)
    snapshot(sorted(data, key=get_message), json=True)


def test_api_context(
    test_client: FlaskClient,
    snapshot: SnapshotFunc,
    example_ledger: FavaLedger,
) -> None:
    response = test_client.get("/long-example/api/context")
    assert_api_error(
        response,
        "Invalid API request: Object missing required field `entry_hash`",
        status=HTTPStatus.BAD_REQUEST,
    )

    response = test_client.get(
        "/long-example/api/context",
        query_string={"entry_hash": "not_found"},
    )
    assert_api_error(
        response,
        'No entry found for hash "not_found"',
        status=HTTPStatus.NOT_FOUND,
        title="EntryNotFoundForHashError",
    )

    balance_entry_hash = hash_entry(
        example_ledger.all_entries_by_type.Balance[0]
    )
    response = test_client.get(
        "/long-example/api/context",
        query_string={"entry_hash": balance_entry_hash},
    )
    data = assert_api_success(response)
    assert isinstance(data, dict)
    assert data["balances_before"]
    assert not data["balances_after"]

    entry_hash = hash_entry(
        next(
            entry
            for entry in example_ledger.all_entries_by_type.Transaction
            if entry.narration == r"Investing 40% of cash in VBMPX"
            and entry.date == datetime.date(2016, 5, 9)
        ),
    )

    response = test_client.get(
        "/long-example/api/context",
        query_string={"entry_hash": entry_hash},
    )
    data = assert_api_success(response)
    snapshot(data, json=True)
    response = test_client.get(
        "/long-example/api/source_slice",
        query_string={"entry_hash": entry_hash},
    )
    data = assert_api_success(response)
    snapshot(data, json=True)

    entry_hash = hash_entry(example_ledger.all_entries[10])
    response = test_client.get(
        "/long-example/api/context",
        query_string={"entry_hash": entry_hash},
    )
    data = assert_api_success(response)
    snapshot(data, json=True)
    assert isinstance(data, dict)
    assert not data.get("balances_before")
    response = test_client.get(
        "/long-example/api/source_slice",
        query_string={"entry_hash": entry_hash},
    )
    data = assert_api_success(response)
    snapshot(data, json=True)


def test_api_payee_accounts(
    test_client: FlaskClient,
    snapshot: SnapshotFunc,
) -> None:
    response = test_client.get("/long-example/api/payee_accounts")
    assert_api_error(response, status=HTTPStatus.BAD_REQUEST)

    response = test_client.get(
        "/long-example/api/payee_accounts",
        query_string={"payee": "EDISON POWER"},
    )
    data = assert_api_success(response)
    assert isinstance(data, list)
    assert data[0] == "Assets:US:BofA:Checking"
    assert data[1] == "Expenses:Home:Electricity"
    snapshot(data, json=True)


def test_api_payee_transaction(
    test_client: FlaskClient,
    snapshot: SnapshotFunc,
) -> None:
    response = test_client.get(
        "/long-example/api/payee_transaction",
        query_string={"payee": "EDISON POWER"},
    )
    data = assert_api_success(response)
    snapshot(data, json=True)


def test_api_narration_transaction(
    test_client: FlaskClient,
) -> None:
    response = test_client.get(
        "/long-example/api/narration_transaction",
        query_string={"narration": "Buying groceries"},
    )
    data = assert_api_success(response)
    assert isinstance(data, dict)
    assert data["date"] == "2016-04-21"
    assert data["narration"] == "Buying groceries"
    assert data["payee"] == "Farmer Fresh"
    assert len(data["postings"]) == 2
    assert data["t"] == "Transaction"


def test_api_imports(
    test_client: FlaskClient,
    snapshot: SnapshotFunc,
) -> None:
    response = test_client.get("/import/api/imports")
    data = assert_api_success(response)
    assert data
    snapshot(data, json=True)

    assert isinstance(data, list)
    importable = next(f for f in data if f["importers"])
    assert importable

    response = test_client.get(
        "/import/api/extract",
        query_string={
            "filename": importable["name"],
            "importer": importable["importers"][0]["importer_name"],
        },
    )
    data = assert_api_success(response)
    snapshot(data, json=True)


def test_api_move_not_a_document(
    test_client: FlaskClient,
    tmp_path: Path,
) -> None:
    """Only documents and files in an import dir may be moved."""
    other_file = tmp_path / "some-other-file"
    other_file.write_text("not a document")

    response = test_client.put(
        "/import/api/move",
        json={
            "account": "Assets:Checking",
            "new_name": "new",
            "filename": str(other_file),
        },
    )
    assert_api_error(
        response,
        f"Not valid document or import file: '{other_file}'.",
        status=HTTPStatus.BAD_REQUEST,
    )
    assert other_file.is_file()


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (["account"], "Expected `object`, got `array`"),
        ("account", "Expected `object`, got `str`"),
        (1, "Expected `object`, got `int`"),
        (None, "Invalid JSON body."),
    ],
)
def test_api_put_invalid_json_body(
    test_client: FlaskClient,
    body: object,
    expected: str,
) -> None:
    """The body of a PUT request needs to be a JSON object."""
    response = test_client.put("/long-example/api/move", json=body)
    assert_api_error(
        response,
        f"Invalid API request: {expected}",
        status=HTTPStatus.BAD_REQUEST,
    )


@pytest.mark.parametrize(
    ("value", "json_type"),
    [(["new"], "array"), ({"a": "new"}, "object"), (1, "int"), (True, "bool")],
)
def test_api_put_incorrect_parameter_type(
    test_client: FlaskClient,
    value: object,
    json_type: str,
) -> None:
    """A parameter that is declared as a string needs to be one."""
    response = test_client.put(
        "/long-example/api/move",
        json={"account": "Assets", "new_name": value, "filename": "old"},
    )
    assert_api_error(
        response,
        "Invalid API request: Expected `str`, got "
        f"`{json_type}` - at `$.new_name`",
        status=HTTPStatus.BAD_REQUEST,
    )


def test_api_move(test_client: FlaskClient) -> None:
    response = test_client.put("/long-example/api/move")
    assert_api_error(
        response,
        "Invalid API request: Invalid JSON body.",
        status=HTTPStatus.BAD_REQUEST,
        title="InvalidJsonRequestError",
    )

    invalid = {"account": "Assets", "new_name": "new", "filename": "old"}
    response = test_client.put("/long-example/api/move", json=invalid)
    assert_api_error(
        response,
        "You need to set a documents folder.",
        status=HTTPStatus.UNPROCESSABLE_ENTITY,
    )

    response = test_client.put("/import/api/move", json=invalid)
    assert_api_error(response, "Not a valid account: 'Assets'")

    response = test_client.put(
        "/import/api/move",
        json={
            **invalid,
            "account": "Assets:Checking",
        },
    )
    assert_api_error(
        response, "Not a file: 'old'", status=HTTPStatus.UNPROCESSABLE_ENTITY
    )


def test_api_get_source_invalid_unicode(test_client: FlaskClient) -> None:
    response = test_client.get("/invalid-unicode/api/source")
    err_msg = assert_api_error(response)
    assert "The source file contains invalid unicode" in err_msg


def test_api_get_source_unknown_file(test_client: FlaskClient) -> None:
    response = test_client.get(
        "/example/api/source",
        query_string={"filename": "/home/not-one-of-the-includes"},
    )
    err_msg = assert_api_error(response)
    assert "Trying to read a non-source file" in err_msg


def test_api_get_source_slice_unprocessable(
    test_client: FlaskClient, get_ledger: GetFavaLedger
) -> None:
    generated_open_entry = get_ledger("edit-example").all_entries[0]
    entry_hash = hash_entry(generated_open_entry)
    response = test_client.get(
        "/edit-example/api/source_slice",
        query_string={"entry_hash": entry_hash},
    )
    assert_api_error(
        response,
        status=HTTPStatus.UNPROCESSABLE_ENTITY,
    )


def test_api_put_source_bad_request(test_client: FlaskClient) -> None:
    response = test_client.put("/example/api/source")
    assert_api_error(
        response,
        "Invalid API request: Invalid JSON body.",
        status=HTTPStatus.BAD_REQUEST,
    )


def test_api_source(app_in_tmp_dir: Flask) -> None:
    test_client = app_in_tmp_dir.test_client()
    ledger = app_in_tmp_dir.config["LEDGERS"]["edit-example"]
    path = Path(ledger.beancount_file_path)
    url = "/edit-example/api/source"

    source = path.read_text("utf-8")
    changed_source = source + "\n;comment"
    sha256sum = _sha256_str(source)

    # read
    response = test_client.get(url)
    data = assert_api_success(response)
    assert isinstance(data, dict)
    assert data["source"] == source

    # change source
    response = test_client.put(
        url,
        json={
            "file_path": str(path),
            "sha256sum": sha256sum,
            "source": changed_source,
        },
    )
    sha256sum = _sha256_str(changed_source)
    assert_api_success(response, sha256sum)

    # check if the file has been written
    assert path.read_text("utf-8") == changed_source

    # write original source file
    response = test_client.put(
        url,
        json={
            "file_path": str(path),
            "sha256sum": sha256sum,
            "source": source,
        },
    )
    assert_api_success(response)
    assert path.read_text("utf-8") == source


def test_api_source_slice_and_insert_metadata(app_in_tmp_dir: Flask) -> None:
    test_client = app_in_tmp_dir.test_client()
    ledger = app_in_tmp_dir.config["LEDGERS"]["edit-example"]
    path = Path(ledger.beancount_file_path)

    source = path.read_text("utf-8")

    # get entry context and update an entry slice
    first_txn = next(e for e in ledger.all_entries if hasattr(e, "postings"))
    assert first_txn.payee == "Kin Soy"
    entry_hash = hash_entry(first_txn)
    response = test_client.get(
        "/edit-example/api/source_slice",
        query_string={"entry_hash": entry_hash},
    )
    data = assert_api_success(response)
    assert isinstance(data, dict)
    assert "Kin Soy" in data["slice"]

    response = test_client.put(
        "/edit-example/api/source_slice",
        json={
            "entry_hash": entry_hash,
            "sha256sum": data["sha256sum"],
            "source": data["slice"].replace("Kin Soy", "Lorem Ipsum"),
        },
    )
    assert_api_success(response)
    assert diff_strings(source, path.read_text("utf-8")) == [
        '- 2014-01-04 * "Kin Soy" "Eating out with Sue"',
        '+ 2014-01-04 * "Lorem Ipsum" "Eating out with Sue"',
    ]
    ledger.load_file()
    first_txn = next(e for e in ledger.all_entries if hasattr(e, "postings"))
    assert first_txn.payee == "Lorem Ipsum"
    entry_hash = hash_entry(first_txn)

    response = test_client.put(
        "/edit-example/api/attach_document",
        json={
            "entry_hash": entry_hash,
            "filename": "edit-example.beancount",
        },
    )
    assert_api_success(response)
    assert diff_strings(source, path.read_text("utf-8")) == [
        '- 2014-01-04 * "Kin Soy" "Eating out with Sue"',
        '+ 2014-01-04 * "Lorem Ipsum" "Eating out with Sue"',
        '+   document: "edit-example.beancount"',
    ]

    ledger.load_file()
    first_txn = next(e for e in ledger.all_entries if hasattr(e, "postings"))
    assert first_txn.payee == "Lorem Ipsum"
    entry_hash = hash_entry(first_txn)

    ledger.options["documents"] = [str(path.parent)]
    target_path = (
        path.parent
        / "Expenses"
        / "Food"
        / "Restaurant"
        / "2022-12-12 asdf.txt"
    )
    response = test_client.put(
        "/edit-example/api/add_document",
        data={
            "folder": str(path.parent),
            "account": "Expenses:Food:Restaurant",
            "file": (BytesIO(b"asdfasdf"), "2022-12-12 asdf.txt"),
            "hash": entry_hash,
        },
    )
    assert_api_success(response)
    assert target_path.exists()
    assert diff_strings(source, path.read_text("utf-8")) == [
        '- 2014-01-04 * "Kin Soy" "Eating out with Sue"',
        '+ 2014-01-04 * "Lorem Ipsum" "Eating out with Sue"',
        '+   document-2: "2022-12-12 asdf.txt"',
        '+   document: "edit-example.beancount"',
    ]


def test_api_format_source(
    test_client: FlaskClient,
    example_ledger: FavaLedger,
) -> None:
    path = Path(example_ledger.beancount_file_path)
    url = "/long-example/api/format_source"

    payload = path.read_text("utf-8")

    response = test_client.put(url, json={"source": payload})
    assert_api_success(response, align(payload, 61))


def test_api_format_source_options(
    app: Flask,
    test_client: FlaskClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with app.test_request_context("/long-example/"):
        app.preprocess_request()
        path = Path(g.ledger.beancount_file_path)
        payload = path.read_text("utf-8")

        monkeypatch.setattr(g.ledger.fava_options, "currency_column", 90)

        response = test_client.put(
            "/long-example/api/format_source",
            json={"source": payload},
        )
        assert_api_success(response, align(payload, 90))


def test_api_source_slice_delete(app_in_tmp_dir: Flask) -> None:
    test_client = app_in_tmp_dir.test_client()
    ledger = app_in_tmp_dir.config["LEDGERS"]["edit-example"]
    path = Path(ledger.beancount_file_path)

    contents = path.read_text("utf-8")
    assert '2016-05-03 * "Chichipotle" "Eating out with Joe"' in contents

    url = "/edit-example/api/source_slice"
    # test bad request
    response = test_client.delete(url)
    assert_api_error(
        response,
        "Invalid API request: Object missing required field `entry_hash`",
        status=HTTPStatus.BAD_REQUEST,
    )

    entry = ledger.all_entries[-1]
    entry_hash = hash_entry(entry)
    _entry_source, sha256sum = get_entry_slice(entry)

    # delete entry
    response = test_client.delete(
        url,
        query_string={"entry_hash": entry_hash, "sha256sum": sha256sum},
    )
    assert_api_success(response, f"Deleted entry {entry_hash}.")
    assert (
        '2016-05-03 * "Chichipotle" "Eating out with Joe"'
        not in path.read_text("utf-8")
    )


def test_api_add_entries(
    app: Flask,
    test_client: FlaskClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with app.test_request_context("/long-example/"):
        app.preprocess_request()
        test_file = tmp_path / "test_file"
        test_file.touch()
        monkeypatch.setattr(g.ledger, "beancount_file_path", str(test_file))

        entries = [
            {
                "t": "Transaction",
                "date": "2017-12-12",
                "flag": "*",
                "payee": "Test3",
                "tags": [],
                "links": [],
                "narration": "",
                "meta": {"filename": "/path/to/import.csv", "lineno": 42},
                "postings": [
                    {
                        "account": "Assets:US:ETrade:Cash",
                        "amount": "100 USD",
                        "meta": {"lineno": 1},
                    },
                    {"account": "Assets:US:ETrade:GLD"},
                ],
            },
            {
                "t": "Transaction",
                "date": "2017-01-12",
                "flag": "*",
                "payee": "Test1",
                "tags": [],
                "links": [],
                "narration": "",
                "meta": {},
                "postings": [
                    {"account": "Assets:US:ETrade:Cash", "amount": "100 USD"},
                    {"account": "Assets:US:ETrade:GLD"},
                ],
            },
            {
                "t": "Transaction",
                "date": "2017-02-12",
                "flag": "*",
                "payee": "Test",
                "tags": [],
                "links": [],
                "narration": "Test",
                "meta": {},
                "postings": [
                    {"account": "Assets:US:ETrade:Cash", "amount": "100 USD"},
                    {"account": "Assets:US:ETrade:GLD"},
                ],
            },
        ]

        url = "/long-example/api/add_entries"

        err = test_client.put(url, json={"entries": "string"})
        assert_api_error(
            err,
            "Invalid API request: Expected `array`, got `str`"
            " - at `$.entries`",
            status=HTTPStatus.BAD_REQUEST,
        )

        response = test_client.put(url, json={"entries": entries})
        assert_api_success(response, "Stored 3 entries.")

        assert (
            test_file.read_text("utf-8")
            == """
2017-01-12 * "Test1" ""
  Assets:US:ETrade:Cash                                 100 USD
  Assets:US:ETrade:GLD

2017-02-12 * "Test" "Test"
  Assets:US:ETrade:Cash                                 100 USD
  Assets:US:ETrade:GLD

2017-12-12 * "Test3" ""
  Assets:US:ETrade:Cash                                 100 USD
  Assets:US:ETrade:GLD
"""
        )


@pytest.mark.parametrize(
    ("query_string", "name"),
    [
        ("balances from year = 2014", "balances"),
        ("select sum(day)", "sum"),
        ("journal from year = 2014 and month = 1", "journal"),
        (
            (
                "select day, position, units(position), balance, payee, tags"
                " from year = 2014 and month = 1"
            ),
            "misc",
        ),
        (".help", "help"),
    ],
)
def test_api_query_result(
    query_string: str,
    name: str,
    test_client: FlaskClient,
    snapshot: SnapshotFunc,
) -> None:
    response = test_client.get(
        "/long-example/api/query",
        query_string={"query_string": query_string},
    )
    data = assert_api_success(response)
    snapshot(data, name=name, json=True)


def test_api_query_result_types(
    test_client: FlaskClient,
) -> None:
    query_string = (
        "select day, position, units(position), balance, payee, tags, "
        "entry, meta from year = 2014 and month = 1"
    )
    response = test_client.get(
        "/long-example/api/query",
        query_string={"query_string": query_string},
    )
    assert_api_success(response)


def test_api_query_result_error(test_client: FlaskClient) -> None:
    response = test_client.get(
        "/long-example/api/query",
        query_string={"query_string": "nononono"},
    )
    msg = assert_api_error(response)
    assert "Query parse error: syntax error" in msg


def test_api_help(test_client: FlaskClient) -> None:
    response = test_client.get(
        "/long-example/api/help",
        query_string={"page_slug": "_index"},
    )
    data = assert_api_success(response)
    assert isinstance(data, dict)
    assert f"Fava <code>{version('fava')}</code>" in data["html"]
    assert ["_index", "Index"] in data["pages"]


def test_api_help_not_found(test_client: FlaskClient) -> None:
    response = test_client.get(
        "/long-example/api/help",
        query_string={"page_slug": "asdfasdf"},
    )
    assert_api_error(response, "Not found.", status=HTTPStatus.NOT_FOUND)


def test_api_commodities_empty(
    test_client: FlaskClient,
) -> None:
    response = test_client.get(
        "/long-example/api/commodities?time=3000",
    )
    data = assert_api_success(response)
    assert not data


def test_api_documents_page_scope_and_pagination(
    test_client: FlaskClient,
) -> None:
    first = assert_api_success(
        test_client.get(
            "/example/api/documents_page",
            query_string={"page": 1, "per_page": 1, "a": "Expenses"},
        )
    )
    second = assert_api_success(
        test_client.get(
            "/example/api/documents_page",
            query_string={"page": 2, "per_page": 1, "a": "Expenses"},
        )
    )
    assert first["total_entries"] == 3
    assert first["page_size"] == 1
    assert len(first["documents"]) == len(second["documents"]) == 1
    assert first["documents"][0] != second["documents"][0]
    assert first["accounts"] == [{"account": "Expenses:Food", "count": 3}]

    # `account` is the global ledger filter; `a` is applied locally after
    # account totals are calculated.
    filtered = assert_api_success(
        test_client.get(
            "/example/api/documents_page",
            query_string={
                "account": "Expenses:Food",
                "a": "Expenses:Other",
                "per_page": 1,
            },
        )
    )
    assert filtered["total_entries"] == 0
    assert filtered["accounts"] == [{"account": "Expenses:Food", "count": 3}]


def test_report_page_overviews_can_be_omitted(
    test_client: FlaskClient,
) -> None:
    for path, params, overview_fields in (
        ("/example/api/documents_page", {"a": "Expenses"}, ("accounts",)),
        (
            "/long-example/api/events_page",
            {},
            (
                "types",
                "chart_events",
                "total_events",
                "chart_events_sampled",
                "chart_total_events",
            ),
        ),
        (
            "/example/api/commodity_report",
            {"base": "USD", "quote": "EUR"},
            (
                "pairs",
                "chart_prices",
                "chart_prices_sampled",
                "chart_total_prices",
            ),
        ),
    ):
        first = assert_api_success(
            test_client.get(
                path,
                query_string={**params, "page": 1, "per_page": 1},
            )
        )
        later = assert_api_success(
            test_client.get(
                path,
                query_string={
                    **params,
                    "page": 2,
                    "per_page": 1,
                    "include_overview": "false",
                },
            )
        )
        assert all(first[field] is not None for field in overview_fields)
        assert all(later[field] is None for field in overview_fields)


def test_report_selector_caches_are_bounded(
    test_client: FlaskClient,
    get_ledger: GetFavaLedger,
) -> None:
    ledger = get_ledger("long-example")
    ledger._report_view_caches.clear()
    document_accounts = ("Expenses", "Assets", "Liabilities")
    event_types = ("employer", "location", "residence")
    try:
        for account in document_accounts:
            assert_api_success(
                test_client.get(
                    "/long-example/api/documents_page",
                    query_string={"a": account},
                )
            )
        document_cache = ledger._report_view_caches["document_subsets"]
        assert len(document_cache) == 2
        document_keys = cast(
            "list[tuple[object, ...]]", list(document_cache.keys())
        )
        assert {key[2] for key in document_keys} == set(document_accounts[-2:])

        for event_type in event_types:
            assert_api_success(
                test_client.get(
                    "/long-example/api/events_page",
                    query_string={"event_type": event_type},
                )
            )
        event_cache = ledger._report_view_caches["event_subsets"]
        assert len(event_cache) == 2
        event_keys = cast("list[tuple[object, ...]]", list(event_cache.keys()))
        assert {key[2] for key in event_keys} == set(event_types[-2:])
    finally:
        ledger._report_view_caches.clear()


def test_api_documents_page_validates_query(
    test_client: FlaskClient,
) -> None:
    response = test_client.get("/example/api/documents_page?sort=bogus")
    assert_api_error(
        response,
        "Invalid API request: sort must be one of date, name",
        status=HTTPStatus.BAD_REQUEST,
    )


def test_api_documents_page_sorts_displayed_names(
    test_client: FlaskClient,
    get_ledger: GetFavaLedger,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = get_ledger("example")
    original_entries = ledger.all_entries
    date = datetime.date(2012, 12, 15)
    extra_documents = (
        data.Document(
            {},
            date,
            "Expenses:Food",
            "2012-12-15 zebra.pdf",
            frozenset(),
            frozenset(),
        ),
        data.Document(
            {}, date, "Expenses:Food", "alpha.pdf", frozenset(), frozenset()
        ),
    )
    ledger._report_view_caches.clear()
    monkeypatch.setattr(
        ledger, "all_entries", (*original_entries, *extra_documents)
    )
    ledger.get_filtered.cache_clear()
    try:
        ascending = assert_api_success(
            test_client.get(
                "/example/api/documents_page",
                query_string={"sort": "name", "order": "asc", "per_page": 10},
            )
        )
        descending = assert_api_success(
            test_client.get(
                "/example/api/documents_page",
                query_string={"sort": "name", "order": "desc", "per_page": 10},
            )
        )

        def displayed_name(document: dict[str, Any]) -> str:
            basename = Path(document["filename"]).name
            if basename.startswith(document["date"]):
                basename = basename[11:]
            return basename.casefold()

        names = [
            displayed_name(document) for document in ascending["documents"]
        ]
        assert names == sorted(names)
        assert names == [
            displayed_name(document)
            for document in reversed(descending["documents"])
        ]
        assert "zebra.pdf" in names
    finally:
        ledger.get_filtered.cache_clear()
        ledger._report_view_caches.clear()


def test_api_empty_report_pages_and_invalid_pagination(
    test_client: FlaskClient,
) -> None:
    for endpoint in ("documents_page", "events_page", "commodity_report"):
        empty = assert_api_success(
            test_client.get(f"/long-example/api/{endpoint}?time=3000")
        )
        assert empty["total_entries"] == 0
        assert empty["total_pages"] == 1
        for page in (0, 2):
            response = test_client.get(
                f"/long-example/api/{endpoint}",
                query_string={"time": "3000", "page": page},
            )
            if page == 0:
                assert_api_error(
                    response,
                    "Invalid API request: page must be at least 1",
                    status=HTTPStatus.BAD_REQUEST,
                )
            else:
                assert_api_error(response, status=HTTPStatus.NOT_FOUND)

    bad_order = test_client.get("/long-example/api/events_page?order=sideways")
    assert_api_error(
        bad_order,
        "Invalid API request: order must be 'asc' or 'desc'",
        status=HTTPStatus.BAD_REQUEST,
    )
    bad_page_size = test_client.get(
        "/long-example/api/documents_page?per_page=0"
    )
    assert_api_error(
        bad_page_size,
        "Invalid API request: per_page must be between 1 and 500",
        status=HTTPStatus.BAD_REQUEST,
    )
    incomplete_pair = test_client.get(
        "/long-example/api/commodity_report?base=USD"
    )
    assert_api_error(
        incomplete_pair,
        "Invalid API request: base and quote must be provided together",
        status=HTTPStatus.BAD_REQUEST,
    )


def test_api_events_page_and_sort_cache_keys(
    test_client: FlaskClient,
) -> None:
    desc = assert_api_success(
        test_client.get(
            "/long-example/api/events_page",
            query_string={"per_page": 1, "sort": "date", "order": "desc"},
        )
    )
    asc = assert_api_success(
        test_client.get(
            "/long-example/api/events_page",
            query_string={"per_page": 1, "sort": "date", "order": "asc"},
        )
    )
    assert desc["total_events"] >= 2
    assert desc["total_entries"] == desc["total_events"]
    assert len(desc["chart_events"]) == desc["total_events"]
    assert desc["chart_events_sampled"] is False
    assert asc["events"][0]["date"] <= desc["events"][0]["date"]
    assert (
        sum(event_type["count"] for event_type in asc["types"])
        == asc["total_events"]
    )

    employer = assert_api_success(
        test_client.get(
            "/long-example/api/events_page",
            query_string={"event_type": "employer", "per_page": 1},
        )
    )
    assert employer["total_events"] == asc["total_events"]
    assert employer["total_entries"] == 1
    assert employer["events"][0]["type"] == "employer"


@pytest.mark.parametrize(
    ("sort", "order"),
    [("description", "asc"), ("description", "desc"), ("type", "asc")],
)
def test_api_events_page_sorts_all_columns(
    test_client: FlaskClient,
    sort: str,
    order: str,
) -> None:
    response = assert_api_success(
        test_client.get(
            "/long-example/api/events_page",
            query_string={"sort": sort, "order": order, "per_page": 100},
        )
    )
    values = [event[sort].casefold() for event in response["events"]]
    assert values == sorted(values, reverse=order == "desc")


def test_api_events_page_samples_large_chart_and_preserves_types(
    test_client: FlaskClient,
    get_ledger: GetFavaLedger,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = get_ledger("long-example")
    event_types = ("rare", "common")
    events = tuple(
        data.Event(
            {},
            datetime.date(2000, 1, 1) + datetime.timedelta(days=index),
            event_types[0] if index == 1 else event_types[1],
            f"event-{index:04}",
        )
        for index in range(4001)
    )
    ledger._report_view_caches.clear()
    monkeypatch.setattr(ledger, "all_entries", events)
    ledger.get_filtered.cache_clear()
    try:
        report = assert_api_success(
            test_client.get("/long-example/api/events_page?per_page=1")
        )
        assert report["total_events"] == 4001
        assert report["chart_events_sampled"] is True
        assert report["chart_total_events"] == 4001
        assert len(report["chart_events"]) == 2000
        assert {event["type"] for event in report["chart_events"]} == set(
            event_types
        )
        dates = [
            datetime.date.fromisoformat(event["date"])
            for event in report["chart_events"]
        ]
        assert dates[0] == datetime.date(2000, 1, 1)
        assert dates[-1] == datetime.date(2000, 1, 1) + datetime.timedelta(
            days=4000
        )
        assert dates[1] == datetime.date(2000, 1, 2)
    finally:
        ledger.get_filtered.cache_clear()
        ledger._report_view_caches.clear()


def test_sample_events_caps_samples_when_type_count_exceeds_limit() -> None:
    events = tuple(
        data.Event(
            {},
            datetime.date(2000, 1, 1) + datetime.timedelta(days=index),
            f"type-{index}",
            f"event-{index}",
        )
        for index in range(2001)
    )

    sampled = _sample_events(cast("Sequence[Event]", events))

    assert len(sampled) == 2000
    assert sampled[0] == events[0]
    assert sampled[-1] == events[-1]


def test_sample_events_with_fully_protected_indices_stays_bounded() -> None:
    events = tuple(
        data.Event(
            {},
            datetime.date(2000, 1, 1) + datetime.timedelta(days=index),
            "shared" if index in {0, 2000} else f"type-{index}",
            f"event-{index}",
        )
        for index in range(2001)
    )

    sampled = _sample_events(cast("Sequence[Event]", events))

    assert len(sampled) == 2000
    assert sampled[0] == events[0]
    assert sampled[-1] == events[-1]


@pytest.mark.parametrize("order", ["asc", "desc"])
def test_api_commodity_report_sorts_by_price(
    test_client: FlaskClient,
    order: str,
) -> None:
    report = assert_api_success(
        test_client.get(
            "/example/api/commodity_report",
            query_string={
                "base": "USD",
                "quote": "EUR",
                "sort": "price",
                "order": order,
            },
        )
    )
    prices = [float(point[1]) for point in report["prices"]]
    assert prices == sorted(prices, reverse=order == "desc")


def test_api_commodity_report_samples_large_price_chart(
    test_client: FlaskClient,
    get_ledger: GetFavaLedger,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = get_ledger("example")
    pair = ledger.commodity_pairs()[0]
    prices = tuple(
        (
            datetime.date(2000, 1, 1) + datetime.timedelta(days=index),
            Decimal(index + 1),
        )
        for index in range(2001)
    )
    ledger._report_view_caches.clear()
    monkeypatch.setattr(
        FilteredLedger,
        "prices",
        lambda _filtered, _base, _quote: prices,
    )
    try:
        report = assert_api_success(
            test_client.get(
                "/example/api/commodity_report",
                query_string={
                    "base": pair[0],
                    "quote": pair[1],
                    "per_page": 1,
                },
            )
        )
        assert report["total_entries"] == 2001
        assert report["chart_prices_sampled"] is True
        assert report["chart_total_prices"] == 2001
        assert len(report["chart_prices"]) == 2000
        assert report["chart_prices"][0][0] == "2000-01-01"
        assert report["chart_prices"][-1][0] == "2005-06-23"
    finally:
        ledger._report_view_caches.clear()


def test_api_events_page_rejects_bad_page_size(
    test_client: FlaskClient,
) -> None:
    response = test_client.get("/long-example/api/events_page?per_page=501")
    assert_api_error(
        response,
        "Invalid API request: per_page must be between 1 and 500",
        status=HTTPStatus.BAD_REQUEST,
    )


def test_api_commodity_report_pages_selected_pair(
    test_client: FlaskClient,
) -> None:
    first = assert_api_success(
        test_client.get(
            "/example/api/commodity_report",
            query_string={
                "base": "USD",
                "quote": "EUR",
                "page": 1,
                "per_page": 1,
                "sort": "date",
                "order": "asc",
            },
        )
    )
    second = assert_api_success(
        test_client.get(
            "/example/api/commodity_report",
            query_string={
                "base": "USD",
                "quote": "EUR",
                "page": 2,
                "per_page": 1,
                "sort": "date",
                "order": "asc",
            },
        )
    )
    assert first["base"] == "USD"
    assert first["quote"] == "EUR"
    assert first["total_entries"] == 2
    assert first["pairs"] == [{"base": "USD", "quote": "EUR", "count": 2}]
    assert len(first["prices"]) == len(second["prices"]) == 1
    assert first["prices"][0][0] < second["prices"][0][0]
    assert len(first["chart_prices"]) == 2
    assert first["chart_total_prices"] == 2


def test_api_commodity_report_defaults_to_first_visible_pair(
    test_client: FlaskClient,
) -> None:
    report = assert_api_success(
        test_client.get("/example/api/commodity_report")
    )
    first_pair = report["pairs"][0]
    assert (report["base"], report["quote"]) == (
        first_pair["base"],
        first_pair["quote"],
    )


def test_api_commodity_report_validates_pair(
    test_client: FlaskClient,
) -> None:
    response = test_client.get(
        "/example/api/commodity_report?base=UNKNOWN&quote=OTHER"
    )
    assert_api_error(
        response,
        "Invalid API request: unknown commodity pair: UNKNOWN/OTHER",
        status=HTTPStatus.BAD_REQUEST,
    )


def test_api_journal_page_not_found(
    test_client: FlaskClient,
) -> None:
    response = test_client.get(
        "/long-example/api/journal_page?page=1000&order=desc"
    )
    assert_api_error(response, status=HTTPStatus.NOT_FOUND)


def test_api_journal_page_invalid_page(
    test_client: FlaskClient,
) -> None:
    response = test_client.get(
        "/long-example/api/journal_page?page=asdf&order=desc"
    )
    assert_api_error(
        response,
        "Invalid API request: Expected `int`, got `str` - at `$.page`",
        status=HTTPStatus.BAD_REQUEST,
    )


def test_api_journal_page_slices_and_filters(
    test_client: FlaskClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = test_client.get(
        "/long-example/api/journal_page",
        query_string={
            "page": 1,
            "order": "asc",
            "sort": "narration",
            "show": "transaction,cleared,pending,other",
            "per_page": 2,
        },
    )
    data = assert_api_success(response)
    assert isinstance(data, dict)
    assert data["page"] == 1
    assert data["page_size"] == 2
    assert data["total_entries"] >= 2
    assert data["total_pages"] == (data["total_entries"] + 1) // 2
    assert data["journal"].count("<li class='transaction") == 2

    def fail_if_view_is_recomputed(*_args: object, **_kwargs: object) -> None:
        raise AssertionError

    monkeypatch.setattr(
        "fava.json_api._journal_sort_value", fail_if_view_is_recomputed
    )

    cached = assert_api_success(
        test_client.get(
            "/long-example/api/journal_page",
            query_string={
                "page": 1,
                "order": "asc",
                "sort": "narration",
                "show": "transaction,cleared,pending,other",
                "per_page": 2,
            },
        )
    )
    assert cached == data

    empty = assert_api_success(
        test_client.get(
            "/long-example/api/journal_page",
            query_string={"page": 1, "show": ""},
        )
    )
    assert isinstance(empty, dict)
    assert empty["total_entries"] == 0
    assert empty["total_pages"] == 1
    assert empty["journal"] == ""

    cached_empty = assert_api_success(
        test_client.get(
            "/long-example/api/journal_page",
            query_string={"page": 1, "show": ""},
        )
    )
    assert cached_empty == empty


@pytest.mark.parametrize("sort", ["flag", "narration", "change"])
def test_api_journal_page_sorts_visible_columns(
    test_client: FlaskClient, sort: str
) -> None:
    data = assert_api_success(
        test_client.get(
            "/example/api/journal_page",
            query_string={
                "page": 1,
                "sort": sort,
                "order": "asc",
                "show": (
                    "transaction,cleared,pending,other,close,open,custom,"
                    "document,note,balance,budget,query,pad,statement"
                ),
                "per_page": 100,
            },
        )
    )
    assert isinstance(data, dict)
    assert data["total_entries"] > 0
    assert data["journal"]


def test_api_custom_journal_sort_uses_custom_type(
    test_client: FlaskClient,
) -> None:
    data = assert_api_success(
        test_client.get(
            "/example/api/journal_page",
            query_string={
                "page": 1,
                "sort": "narration",
                "order": "asc",
                "show": "custom,budget",
                "per_page": 100,
            },
        )
    )
    assert isinstance(data, dict)
    assert data["journal"].index("<strong>budget</strong>") < data[
        "journal"
    ].index("<strong>type</strong>")


def test_api_journal_page_filters_entry_subtypes(
    test_client: FlaskClient,
) -> None:
    cleared = assert_api_success(
        test_client.get(
            "/example/api/journal_page",
            query_string={
                "page": 1,
                "show": "transaction,cleared,metadata,postings",
                "per_page": 100,
            },
        )
    )
    assert isinstance(cleared, dict)
    assert cleared["total_entries"] > 0
    assert "Payee" in cleared["journal"]
    assert "transaction ! pending" not in cleared["journal"]

    spaced_filters = assert_api_success(
        test_client.get(
            "/example/api/journal_page",
            query_string={
                "page": 1,
                "show": " transaction , cleared , metadata , postings ",
                "per_page": 100,
            },
        )
    )
    assert isinstance(spaced_filters, dict)
    assert spaced_filters["total_entries"] == cleared["total_entries"]

    budgets = assert_api_success(
        test_client.get(
            "/example/api/journal_page",
            query_string={"page": 1, "show": "custom,budget", "per_page": 100},
        )
    )
    assert isinstance(budgets, dict)
    assert budgets["total_entries"] == 2
    assert "budget" in budgets["journal"]

    discovered = assert_api_success(
        test_client.get(
            "/example/api/journal_page",
            query_string={
                "page": 1,
                "show": "document,discovered",
                "per_page": 100,
            },
        )
    )
    assert isinstance(discovered, dict)
    assert discovered["total_entries"] == 3
    assert "receipt.pdf" in discovered["journal"]


@pytest.mark.parametrize(
    ("query", "detail"),
    [
        ({"page": 0}, "page must be at least 1"),
        (
            {"sort": "unknown"},
            "sort must be one of change, date, flag, narration",
        ),
        ({"per_page": 1001}, "per_page must be between 1 and 1000"),
        ({"order": "sideways"}, "order must be 'asc' or 'desc'"),
        (
            {"show": "transaction,invalid"},
            "unknown journal entry type(s): invalid",
        ),
    ],
)
def test_api_journal_page_rejects_invalid_options(
    test_client: FlaskClient,
    query: dict[str, object],
    detail: str,
) -> None:
    response = test_client.get(
        "/long-example/api/journal_page",
        query_string={"page": 1, **query},
    )
    assert_api_error(
        response,
        f"Invalid API request: {detail}",
        status=HTTPStatus.BAD_REQUEST,
    )


def test_api_account_journal_pages_preserve_running_balances(
    test_client: FlaskClient,
) -> None:
    query = {"a": "Assets:US:ETrade:Cash"}
    full = assert_api_success(
        test_client.get("/long-example/api/account_report", query_string=query)
    )
    assert isinstance(full, dict)
    paged = []
    page = 1
    while True:
        data = assert_api_success(
            test_client.get(
                "/long-example/api/journal_page",
                query_string={**query, "page": page, "per_page": 1},
            )
        )
        assert isinstance(data, dict)
        paged.append(data["journal"])
        if page == data["total_pages"]:
            break
        page += 1

    assert "journal" in full
    assert "".join(paged) == full["journal"]

    changed = assert_api_success(
        test_client.get(
            "/long-example/api/journal_page",
            query_string={
                **query,
                "page": 1,
                "sort": "change",
                "per_page": 100,
            },
        )
    )
    assert isinstance(changed, dict)
    assert changed["total_entries"] > 0
    assert changed["journal"]


def test_api_account_report_can_skip_journal(
    test_client: FlaskClient,
) -> None:
    data = assert_api_success(
        test_client.get(
            "/long-example/api/account_report",
            query_string={"a": "Assets:Cash", "include_journal": "false"},
        )
    )
    assert isinstance(data, dict)
    assert data["journal"] == ""
    assert data["charts"]


def test_api_account_report_empty(
    test_client: FlaskClient,
) -> None:
    """A filter matching no entries gives empty interval balances."""
    response = test_client.get(
        "/long-example/api/account_report",
        query_string={"a": "Assets", "r": "balances", "filter": "payee:asdf"},
    )
    data = assert_api_success(response)
    assert isinstance(data, dict)
    assert data == {
        "budgets": {},
        "charts": data["charts"],
        "dates": [],
        "interval_balances": [],
    }


def test_api_filter_error(
    test_client: FlaskClient,
) -> None:
    response = test_client.get(
        "/long-example/api/commodities?time=20",
    )
    assert_api_error(response, status=HTTPStatus.BAD_REQUEST)


@pytest.mark.parametrize(
    ("name", "url"),
    [
        ("commodities", "/long-example/api/commodities"),
        ("documents", "/example/api/documents"),
        ("events", "/long-example/api/events"),
        ("journal", "/example/api/journal"),
        ("income_statement", "/long-example/api/income_statement?time=2014"),
        ("narrations", "/long-example/api/narrations"),
        ("trial_balance", "/long-example/api/trial_balance?time=2014"),
        ("balance_sheet", "/long-example/api/balance_sheet"),
        (
            "balance_sheet_with_cost",
            "/long-example/api/balance_sheet?conversion=at_value",
        ),
        (
            "account_report_off_by_one_journal",
            (
                "/off-by-one/api/account_report"
                "?interval=day&conversion=at_value&a=Assets"
            ),
        ),
        (
            "account_report_off_by_one",
            (
                "/off-by-one/api/account_report"
                "?interval=day&conversion=at_value&a=Assets&r=balances"
            ),
        ),
        ("statistics", "/long-example/api/statistics"),
        ("options", "/long-example/api/options"),
    ],
)
def test_api(
    test_client: FlaskClient,
    snapshot: SnapshotFunc,
    name: str,
    url: str,
) -> None:
    response = test_client.get(url)
    data = assert_api_success(response)
    assert data
    snapshot(data, name=name, json=True)
