"""JSON API.

This module contains the url endpoints of the JSON API that is used by the web
interface for asynchronous functionality.
"""

from __future__ import annotations

import logging
import shutil
from abc import ABC
from abc import abstractmethod
from collections import Counter
from collections.abc import Sequence
from decimal import Decimal
from functools import wraps
from http import HTTPStatus
from inspect import Parameter
from inspect import signature
from pathlib import Path
from pprint import pformat
from typing import cast
from typing import TYPE_CHECKING
from typing import TypeVar

import msgspec
from flask import Blueprint
from flask import get_template_attribute
from flask import jsonify
from flask import request
from flask_babel import gettext
from msgspec import Struct
from msgspec.structs import astuple

from fava import _structs  # noqa: TC001 - needed for msgspec
from fava.beans.abc import Directive
from fava.beans.abc import Document
from fava.beans.abc import Event
from fava.beans.abc import Transaction
from fava.beans.account import account_tester
from fava.context import g
from fava.core import EntryNotFoundForHashError
from fava.core.conversion import UNITS
from fava.core.documents import filepath_in_document_folder
from fava.core.documents import is_document_or_import_file
from fava.core.fava_options import All_OPTS
from fava.core.file import GeneratedEntryError
from fava.core.file import get_entry_slice
from fava.core.filters import FilterError
from fava.core.group_entries import group_entries_by_type
from fava.core.ingest import filepath_in_primary_imports_folder
from fava.core.inventory import SimpleCounterInventory
from fava.core.misc import align
from fava.helpers import FavaAPIError
from fava.internal_api import ChartApi
from fava.internal_api import get_errors
from fava.internal_api import get_ledger_data
from fava.serialisation import deserialise
from fava.serialisation import serialise

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Callable
    from collections.abc import Mapping
    from datetime import date
    from typing import Literal

    from flask.wrappers import Response
    from werkzeug.datastructures import FileStorage

    from fava.core import FilteredLedger
    from fava.core.ingest import FileImporters
    from fava.core.query import QueryResultTable
    from fava.core.query import QueryResultText
    from fava.core.tree import SerialisedTreeNode
    from fava.internal_api import ChartData
    from fava.util.date import DateRange


json_api = Blueprint("json_api", __name__)
log = logging.getLogger(__name__)


class ProblemDetails(Struct, frozen=True):
    """Error response object structure (Problem Details, RFC 9457)."""

    title: str
    status: int
    detail: str


class SuccessResponse(Struct, frozen=True):
    """Response structure."""

    data: object
    mtime: str


def json_err(error: Exception, status: HTTPStatus) -> Response:
    """Jsonify the error as a RFC 9457 Problem Details object.

    The name of the exception class is used as the title and the error
    message as the detail.
    """
    res = jsonify(
        ProblemDetails(type(error).__name__, status.value, str(error))
    )
    res.status = status
    res.content_type = "application/problem+json"
    return res


class FavaJSONAPIError(ABC, FavaAPIError):
    """An error with a HTTPStatus."""

    @property
    @abstractmethod
    def status(self) -> HTTPStatus:
        """HTTP status that should be used for the response."""


class ValidationError(FavaJSONAPIError):
    """Validation of data failed."""

    status = HTTPStatus.BAD_REQUEST

    def __init__(self, reason: str) -> None:
        super().__init__(f"Invalid API request: {reason}")


class InvalidJsonRequestError(ValidationError):
    """Invalid JSON body."""

    def __init__(self) -> None:
        super().__init__(self.__doc__ or "")


class NotFoundError(FavaJSONAPIError):
    """Not found."""

    status = HTTPStatus.NOT_FOUND


class TargetPathAlreadyExistsError(FavaJSONAPIError):
    """The given path already exists."""

    status = HTTPStatus.CONFLICT

    def __init__(self, path: Path) -> None:
        super().__init__(f"{path} already exists.")


class DocumentDirectoryMissingError(FavaJSONAPIError):
    """You need to set a documents folder."""

    status = HTTPStatus.UNPROCESSABLE_ENTITY


class NoFileUploadedError(FavaJSONAPIError):
    """No file uploaded."""

    status = HTTPStatus.BAD_REQUEST


class UploadedFileIsMissingFilenameError(FavaJSONAPIError):
    """Uploaded file is missing filename."""

    status = HTTPStatus.BAD_REQUEST


class NotAValidDocumentOrImportFileError(FavaJSONAPIError):
    """Not valid document or import file."""

    status = HTTPStatus.BAD_REQUEST

    def __init__(self, filename: str) -> None:
        super().__init__(f"Not valid document or import file: '{filename}'.")


class NotAFileError(FavaJSONAPIError):
    """Not a file."""

    status = HTTPStatus.UNPROCESSABLE_ENTITY

    def __init__(self, filename: str) -> None:
        super().__init__(f"Not a file: '{filename}'")


@json_api.errorhandler(FavaAPIError)
def _(error: FavaAPIError) -> Response:
    log.error("Encountered FavaAPIError.", exc_info=error)
    return json_err(error, HTTPStatus.INTERNAL_SERVER_ERROR)


@json_api.errorhandler(FavaJSONAPIError)
def _(error: FavaJSONAPIError) -> Response:
    return json_err(error, error.status)


@json_api.errorhandler(FilterError)
def _(error: FilterError) -> Response:
    return json_err(error, HTTPStatus.BAD_REQUEST)


@json_api.errorhandler(OSError)
def _(error: OSError) -> Response:  # pragma: no cover
    log.error("Encountered OSError.", exc_info=error)
    return json_err(error, HTTPStatus.INTERNAL_SERVER_ERROR)


@json_api.errorhandler(EntryNotFoundForHashError)
def _(error: EntryNotFoundForHashError) -> Response:
    return json_err(error, HTTPStatus.NOT_FOUND)


@json_api.errorhandler(GeneratedEntryError)
def _(error: GeneratedEntryError) -> Response:
    return json_err(error, HTTPStatus.UNPROCESSABLE_ENTITY)


def _build_param_struct(func: Callable[..., object]) -> type[Struct] | None:
    """Build a msgspec Struct type matching a function's parameters."""
    struct_fields = []
    for param in signature(func).parameters.values():
        assert param.kind == Parameter.POSITIONAL_OR_KEYWORD, (  # noqa: S101
            f"Param {param.name} should be positional"
        )
        struct_fields.append(
            (param.name, param.annotation)
            if param.default is Parameter.empty
            else (param.name, param.annotation, param.default)
        )

    if not struct_fields:
        return None

    return msgspec.defstruct(f"{func.__name__}_params", struct_fields)  # ty:ignore[unresolved-attribute]


def build_json_body_decoder(
    func: Callable[..., object],
) -> Callable[[bytes], Sequence[object]] | None:
    """Build a msgspec-typed decoder for the JSON body of an endpoint."""
    param_struct = _build_param_struct(func)
    if param_struct is None:
        return None
    decoder = msgspec.json.Decoder(param_struct)

    def decode(data: bytes) -> Sequence[object]:
        try:
            return astuple(decoder.decode(data))
        except msgspec.ValidationError as error:
            raise ValidationError(str(error)) from error
        except msgspec.DecodeError as error:
            raise InvalidJsonRequestError from error

    return decode


def build_query_string_decoder(
    func: Callable[..., object],
) -> Callable[[Mapping[str, str]], Sequence[object]] | None:
    """Build a msgspec-typed decoder for an endpoint's query string."""
    param_struct = _build_param_struct(func)
    if param_struct is None:
        return None

    def decode(args: Mapping[str, str]) -> Sequence[object]:
        try:
            return astuple(
                msgspec.convert(args, type=param_struct, strict=False)
            )
        except msgspec.ValidationError as error:
            raise ValidationError(str(error)) from error

    return decode


T = TypeVar("T")


def validate_form(t: type[T]) -> T:
    """Validate the provided form fields to match the passed type."""
    try:
        return msgspec.convert(dict(request.form), t)
    except msgspec.ValidationError as error:
        raise ValidationError(str(error)) from error


def validate_file() -> tuple[FileStorage, str]:
    """Validate the form request contains a file with filename."""
    upload = request.files.get("file", None)

    if upload is None:
        raise NoFileUploadedError
    if not upload.filename:
        raise UploadedFileIsMissingFilenameError

    return (upload, upload.filename)


def api_endpoint(func: Callable[..., object]) -> Callable[[], Response]:
    """Register an API endpoint.

    The part of the function name up to the first underscore determines
    the accepted HTTP method. For GET and DELETE endpoints, the function
    parameters are converted from the URL query string; for PUT endpoints,
    they are decoded from the JSON request body. Both use a msgspec Struct
    generated from the function's parameters for the typed validation.
    """
    method, _, name = func.__name__.partition("_")  # ty:ignore[unresolved-attribute]
    assert method in {"get", "delete", "put"}, (  # noqa: S101
        f"Invalid endpoint function name: {func.__name__}"  # ty: ignore[unresolved-attribute]
    )

    if method == "put":
        decode_body = build_json_body_decoder(func)

        def get_args() -> Sequence[object]:
            return decode_body(request.get_data()) if decode_body else []
    else:
        decode_args = build_query_string_decoder(func)

        def get_args() -> Sequence[object]:
            return decode_args(dict(request.args)) if decode_args else []

    @json_api.route(f"/{name}", methods=[method])
    @wraps(func)
    def _wrapper() -> Response:
        return jsonify(SuccessResponse(func(*get_args()), str(g.ledger.mtime)))

    return _wrapper


@api_endpoint
def get_changed() -> bool:
    """Check for file changes."""
    return g.ledger.changed()


api_endpoint(get_errors)
api_endpoint(get_ledger_data)


@api_endpoint
def get_payee_accounts(payee: str) -> Sequence[str]:
    """Rank accounts for the given payee."""
    return g.ledger.attributes.payee_accounts(payee)


@api_endpoint
def get_query(query_string: str) -> QueryResultTable | QueryResultText:
    """Run a Beancount query."""
    return g.ledger.query_shell.execute_query_serialised(
        g.filtered.entries_with_all_prices, query_string
    )


@api_endpoint
def get_extract(filename: str, importer: str) -> Sequence[object]:
    """Extract entries using the ingest framework."""
    g.ledger.changed()
    entries = g.ledger.ingest.extract(filename, importer)
    return list(map(serialise, entries))


class Context(Struct, frozen=True):
    """Context for an entry."""

    entry: object
    balances_before: Mapping[str, Sequence[str]] | None
    balances_after: Mapping[str, Sequence[str]] | None


@api_endpoint
def get_context(entry_hash: str) -> Context:
    """Entry context."""
    entry, before, after = g.ledger.context(entry_hash)
    return Context(serialise(entry), before, after)


class SourceSlice(Struct, frozen=True):
    """Source slice for an entry."""

    sha256sum: str
    slice: str


@api_endpoint
def get_source_slice(entry_hash: str) -> SourceSlice:
    """Entry slice."""
    entry = g.ledger.get_entry(entry_hash)
    source_slice, sha256sum = get_entry_slice(entry)
    return SourceSlice(sha256sum, source_slice)


@api_endpoint
def put_move(account: str, new_name: str, filename: str) -> str:
    """Move a document."""
    if not g.ledger.options["documents"]:
        raise DocumentDirectoryMissingError

    new_path = filepath_in_document_folder(
        g.ledger.options["documents"][0], account, new_name, g.ledger
    )
    file_path = Path(filename)

    if not file_path.is_file():
        raise NotAFileError(filename)
    if not is_document_or_import_file(filename, g.ledger):
        raise NotAValidDocumentOrImportFileError(filename)
    if new_path.exists():
        raise TargetPathAlreadyExistsError(new_path)

    new_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(filename, new_path)

    return f"Moved {filename} to {new_path}."


@api_endpoint
def get_payee_transaction(payee: str) -> object:
    """Last transaction for the given payee."""
    entry = g.ledger.attributes.payee_transaction(payee)
    return serialise(entry) if entry else None


@api_endpoint
def get_narration_transaction(narration: str) -> object:
    """Last transaction for the given narration."""
    entry = g.ledger.attributes.narration_transaction(narration)
    return serialise(entry) if entry else None


@api_endpoint
def get_narrations() -> Sequence[str]:
    """List of all narrations in the ledger."""
    return g.ledger.attributes.narrations


class SourceFile(Struct, frozen=True):
    """Source slice for an entry."""

    file_path: str
    sha256sum: str
    source: str


@api_endpoint
def get_source(filename: str = "") -> SourceFile:
    """Load one of the source files."""
    file_path = (
        filename
        or g.ledger.fava_options.default_file
        or g.ledger.beancount_file_path
    )
    source, sha256sum = g.ledger.file.get_source(Path(file_path))
    return SourceFile(file_path=file_path, sha256sum=sha256sum, source=source)


@api_endpoint
def put_source(file_path: str, source: str, sha256sum: str) -> str:
    """Write one of the source files and return the updated sha256sum."""
    return g.ledger.file.set_source(Path(file_path), source, sha256sum)


@api_endpoint
def put_source_slice(entry_hash: str, source: str, sha256sum: str) -> str:
    """Write an entry source slice and return the updated sha256sum."""
    return g.ledger.file.save_entry_slice(entry_hash, source, sha256sum)


@api_endpoint
def delete_source_slice(entry_hash: str, sha256sum: str) -> str:
    """Delete an entry source slice."""
    g.ledger.file.delete_entry_slice(entry_hash, sha256sum)
    return f"Deleted entry {entry_hash}."


@api_endpoint
def put_format_source(source: str) -> str:
    """Format beancount file."""
    return align(source, g.ledger.fava_options.currency_column)


class FileDoesNotExistError(FavaJSONAPIError):
    """The given file does not exist."""

    status = HTTPStatus.NOT_FOUND

    def __init__(self, filename: str) -> None:
        super().__init__(f"{filename} does not exist.")


@api_endpoint
def delete_document(filename: str) -> str:
    """Delete a document."""
    if not is_document_or_import_file(filename, g.ledger):
        raise NotAValidDocumentOrImportFileError(filename)

    file_path = Path(filename)
    if not file_path.exists():
        raise FileDoesNotExistError(filename)

    file_path.unlink()
    return f"Deleted {filename}."


class AddDocumentForm(Struct, frozen=True):
    """Required form fields when adding a document."""

    folder: str
    account: str
    hash: str = ""


@api_endpoint
def put_add_document() -> str:
    """Upload a document."""
    if not g.ledger.options["documents"]:
        raise DocumentDirectoryMissingError

    upload, name = validate_file()
    form = validate_form(AddDocumentForm)
    filepath = filepath_in_document_folder(
        form.folder, form.account, name, g.ledger
    )

    if filepath.exists():
        raise TargetPathAlreadyExistsError(filepath)

    filepath.parent.mkdir(parents=True, exist_ok=True)
    upload.save(filepath)

    if form.hash:
        g.ledger.file.insert_metadata(form.hash, "document", filepath.name)
    return f"Uploaded to {filepath}"


@api_endpoint
def put_attach_document(filename: str, entry_hash: str) -> str:
    """Attach a document to an entry."""
    g.ledger.file.insert_metadata(entry_hash, "document", filename)
    return f"Attached '{filename}' to entry."


@api_endpoint
def put_add_entries(
    entries: list[_structs.Balance | _structs.Note | _structs.Transaction],
) -> str:
    """Add multiple entries."""
    g.ledger.file.insert_entries([deserialise(entry) for entry in entries])

    return f"Stored {len(entries)} entries."


@api_endpoint
def put_upload_import_file() -> str:
    """Upload a file for importing."""
    upload, name = validate_file()
    filepath = filepath_in_primary_imports_folder(name, g.ledger)

    if filepath.exists():
        raise TargetPathAlreadyExistsError(filepath)

    filepath.parent.mkdir(parents=True, exist_ok=True)
    upload.save(filepath)

    return f"Uploaded to {filepath}"


########################################################################
# Reports


@api_endpoint
def get_journal() -> Sequence[object]:
    """Get all (filtered) entries."""
    g.ledger.changed()
    return [serialise(e) for e in g.filtered.entries]


class JournalPage(Struct, frozen=True):
    """A rendered journal page."""

    page: int
    total_pages: int
    journal: str
    total_entries: int
    page_size: int
    revision: str


class AccountDocumentCount(Struct, frozen=True):
    """Document count for an account."""

    account: str
    count: int


class EventTypeCount(Struct, frozen=True):
    """Event count for an event type."""

    type: str
    count: int


EventOverview = tuple[
    Sequence[Event], Sequence[EventTypeCount], Sequence[object]
]


class CommodityPairCount(Struct, frozen=True):
    """Price point count for a commodity pair."""

    base: str
    quote: str
    count: int


class DocumentPage(Struct, frozen=True):
    """A bounded page of document directives and account totals."""

    documents: Sequence[object]
    page: int
    page_size: int
    total_entries: int
    total_pages: int
    revision: str
    accounts: Sequence[AccountDocumentCount] | None


class EventPage(Struct, frozen=True):
    """A bounded page of event directives and chart summary data."""

    events: Sequence[object]
    page: int
    page_size: int
    total_entries: int
    total_pages: int
    revision: str
    types: Sequence[EventTypeCount] | None
    chart_events: Sequence[object] | None
    total_events: int | None
    chart_events_sampled: bool | None
    chart_total_events: int | None


class CommodityPricePage(Struct, frozen=True):
    """A bounded page of prices for one commodity pair."""

    pairs: Sequence[CommodityPairCount] | None
    base: str
    quote: str
    prices: Sequence[tuple[date, Decimal]]
    chart_prices: Sequence[tuple[date, Decimal]] | None
    page: int
    page_size: int
    total_entries: int
    total_pages: int
    revision: str
    chart_prices_sampled: bool | None
    chart_total_prices: int | None


_JOURNAL_ENTRY_TYPES = frozenset(
    {
        "balance",
        "budget",
        "cleared",
        "close",
        "commodity",
        "custom",
        "discovered",
        "document",
        "event",
        "linked",
        "metadata",
        "note",
        "open",
        "other",
        "pad",
        "pending",
        "postings",
        "query",
        "statement",
        "transaction",
    }
)
_JOURNAL_SORTS = frozenset({"date", "flag", "narration", "change"})
_MAX_JOURNAL_PAGE_SIZE = 1000
_MAX_REPORT_PAGE_SIZE = 500
_MAX_REPORT_CHART_POINTS = 2000
JournalRow = (
    tuple[int, Directive]
    | tuple[int, Directive, SimpleCounterInventory, SimpleCounterInventory]
)
JournalViewCache = Sequence[JournalRow]


def _journal_sort_value(
    entry: Directive,
    row: JournalRow,
    sort: Literal["flag", "narration", "change"],
) -> str | int | Decimal:
    """Return a sortable journal field for one rendered row."""
    value: str | int | Decimal
    if sort == "flag":
        if isinstance(entry, Transaction):
            value = entry.flag
        else:
            short_type = {
                "balance": "Bal",
                "close": "Close",
                "document": "Doc",
                "note": "Note",
                "open": "Open",
            }
            entry_type = entry.__class__.__name__.lower()
            value = short_type.get(entry_type, entry_type[:3])
    elif sort == "narration":
        if isinstance(entry, Transaction):
            tags = "".join(f" #{tag}" for tag in sorted(entry.tags))
            links = "".join(f" ^{link}" for link in sorted(entry.links))
            description = " ".join(
                part for part in (entry.payee, entry.narration) if part
            )
            value = f"{description}{tags}{links}".casefold()
        elif entry.__class__.__name__.lower() == "custom":
            value = str(getattr(entry, "type", "")).casefold()
        else:
            value = str(
                getattr(entry, "comment", "")
                or getattr(entry, "name", "")
                or getattr(entry, "account", "")
                or ""
            ).casefold()
    elif len(row) == 4:
        value = next(iter(row[2].values()), Decimal(0))
    elif isinstance(entry, Transaction):
        value = next(
            (
                posting.units.number
                for posting in entry.postings
                if posting.units
            ),
            Decimal(0),
        )
    else:
        value = Decimal(0)
    return value


def _journal_entry_is_visible(
    entry: Directive, show_types: frozenset[str]
) -> bool:
    """Apply the same type and subtype visibility rules as the journal UI."""
    entry_type = entry.__class__.__name__.lower()
    if isinstance(entry, Transaction):
        flag_type = {"*": "cleared", "!": "pending"}.get(entry.flag, "other")
        return {"transaction", flag_type} <= show_types
    if (
        entry_type == "custom"
        and getattr(entry, "type", "").casefold() == "budget"
    ):
        return {"custom", "budget"} <= show_types
    if isinstance(entry, Document):
        subtypes = {
            tag
            for tag in (entry.tags or ())
            if tag in {"linked", "discovered"}
        }
        if subtypes:
            return "document" in show_types and bool(subtypes & show_types)
    return entry_type in show_types


def _validate_report_page(page: int, per_page: int) -> int:
    """Validate common page parameters and return page size."""
    if page < 1:
        detail = "page must be at least 1"
        raise _report_validation_error(detail)
    if not 1 <= per_page <= _MAX_REPORT_PAGE_SIZE:
        detail = f"per_page must be between 1 and {_MAX_REPORT_PAGE_SIZE}"
        raise _report_validation_error(detail)
    return per_page


def _report_validation_error(detail: str) -> ValidationError:
    """Build a typed error for a malformed report request."""
    return ValidationError(detail)


def _validate_report_sort(sort: str, choices: Sequence[str]) -> None:
    """Validate a report sort name against its supported values."""
    if sort not in choices:
        detail = f"sort must be one of {', '.join(choices)}"
        raise _report_validation_error(detail)


def _validate_report_order(order: str) -> None:
    """Validate a report sort direction."""
    if order not in {"asc", "desc"}:
        detail = "order must be 'asc' or 'desc'"
        raise _report_validation_error(detail)


def _report_page_slice(
    page: int, per_page: int, total_entries: int
) -> tuple[int, int]:
    """Return a page slice, raising a 404 for a page beyond the result."""
    total_pages = max(1, (total_entries + per_page - 1) // per_page)
    if page > total_pages:
        raise NotFoundError
    start = (page - 1) * per_page
    return start, total_pages


def _sample_sequence(values: Sequence[T], maximum: int) -> tuple[T, ...]:
    """Return an evenly spaced chronological sample of a sequence."""
    if len(values) <= maximum:
        return tuple(values)
    last = len(values) - 1
    return tuple(
        values[index * last // (maximum - 1)] for index in range(maximum)
    )


def _sample_events(events: Sequence[Event]) -> tuple[Event, ...]:
    """Sample events across time while retaining each type when possible."""
    if len(events) <= _MAX_REPORT_CHART_POINTS:
        return tuple(events)

    indexes_by_type: dict[str, int] = {}
    for index, event in enumerate(events):
        indexes_by_type.setdefault(event.type, index)
    last = len(events) - 1

    # Start with a uniform sample that always includes both boundaries.
    selected = {
        sample * last // (_MAX_REPORT_CHART_POINTS - 1)
        for sample in range(_MAX_REPORT_CHART_POINTS)
    }
    selected.update((0, last))

    # Replace nearby, non-boundary sample points with the first occurrence
    # of each type that the uniform sample missed. Keep the existing sample
    # size and its overall date coverage.
    if len(indexes_by_type) <= _MAX_REPORT_CHART_POINTS:
        protected = {0, last}
        protected.update(indexes_by_type.values())
        for index in indexes_by_type.values():
            if index in selected:
                continue
            replaceable = selected - protected
            if not replaceable:
                break
            victim = min(
                replaceable, key=lambda candidate: abs(candidate - index)
            )
            selected.remove(victim)
            selected.add(index)
    return tuple(events[index] for index in sorted(selected))


def _journal_validation_error(detail: str) -> ValidationError:
    """Build a typed API error for a malformed journal query."""
    return ValidationError(detail)


@api_endpoint
def get_journal_page(  # noqa: PLR0912
    page: int,
    order: str = "desc",
    sort: str = "date",
    show: str | None = None,
    per_page: int = _MAX_JOURNAL_PAGE_SIZE,
    a: str | None = None,
) -> JournalPage:
    """Get the HTML contents for a Journal page."""
    if page < 1:
        detail = "page must be at least 1"
        raise _journal_validation_error(detail)
    if sort not in _JOURNAL_SORTS:
        detail = f"sort must be one of {', '.join(sorted(_JOURNAL_SORTS))}"
        raise _journal_validation_error(detail)
    if not 1 <= per_page <= _MAX_JOURNAL_PAGE_SIZE:
        detail = f"per_page must be between 1 and {_MAX_JOURNAL_PAGE_SIZE}"
        raise _journal_validation_error(detail)
    if order not in {"asc", "desc"}:
        detail = "order must be 'asc' or 'desc'"
        raise _journal_validation_error(detail)

    show_types = (
        None
        if show is None
        else frozenset(
            value
            for raw_value in show.split(",")
            if (value := raw_value.strip().lower())
            and value not in {"metadata", "postings"}
        )
    )
    if show_types is not None and not show_types <= _JOURNAL_ENTRY_TYPES:
        invalid = ", ".join(sorted(show_types - _JOURNAL_ENTRY_TYPES))
        detail = f"unknown journal entry type(s): {invalid}"
        raise _journal_validation_error(detail)

    journal_table_contents = get_template_attribute(
        "_journal_table.html", "journal_table_contents"
    )
    if page == 1:
        g.ledger.changed()

    include_children = g.ledger.fava_options.account_journal_include_children
    cache_key = (
        g.filtered,
        g.filtered.revision,
        a,
        str(g.conversion),
        include_children if a else False,
        tuple(sorted(show_types)) if show_types is not None else None,
        sort,
        order,
    )
    view_cache = cast(
        "JournalViewCache | None",
        g.ledger.get_journal_view_cache(cache_key),
    )
    records: Sequence[JournalRow]
    if view_cache is None:
        prepared: list[JournalRow]
        if a:
            prepared = list(
                g.ledger.account_journal(
                    g.filtered,
                    a,
                    g.conversion,
                    with_children=include_children,
                )
            )
        else:
            prepared = [
                (index, entry)
                for index, entry in enumerate(
                    g.filtered.entries_without_prices
                )
            ]

        if show_types is not None:
            prepared = [
                row
                for row in prepared
                if _journal_entry_is_visible(row[1], show_types)
            ]

        prepared.sort(key=lambda row: row[0], reverse=order == "desc")
        if sort != "date":
            prepared.sort(
                key=lambda row: _journal_sort_value(
                    row[1],
                    row,
                    cast("Literal['flag', 'narration', 'change']", sort),
                ),
                reverse=order == "desc",
            )
        records = tuple(prepared)
        g.ledger.set_journal_view_cache(cache_key, records)
    else:
        records = view_cache

    total_entries = len(records)
    total_pages = max(1, (total_entries + per_page - 1) // per_page)
    if page > total_pages:
        raise NotFoundError
    start = (page - 1) * per_page
    page_entries = records[start : start + per_page]
    return JournalPage(
        page=page,
        total_pages=total_pages,
        journal=journal_table_contents(
            page_entries,
            show_change_and_balance=bool(a),
        ),
        total_entries=total_entries,
        page_size=per_page,
        revision=str(g.filtered.revision),
    )


@api_endpoint
def get_events() -> Sequence[object]:
    """Get all (filtered) events."""
    g.ledger.changed()
    return [serialise(e) for e in g.filtered.entries if isinstance(e, Event)]


@api_endpoint
def get_events_page(
    page: int = 1,
    per_page: int = 200,
    sort: str = "date",
    order: str = "desc",
    event_type: str | None = None,
    include_overview: bool = True,  # noqa: FBT001, FBT002
) -> EventPage:
    """Get a page of events and a bounded overview for charts."""
    _validate_report_sort(sort, ("date", "description", "type"))
    _validate_report_order(order)
    _validate_report_page(page, per_page)
    g.ledger.changed()

    filtered = g.filtered
    revision = filtered.revision
    rows_key = (filtered, revision)
    all_events = cast(
        "Sequence[Event] | None",
        g.ledger.get_report_view_cache("event_rows", rows_key),
    )
    if all_events is None:
        all_events = tuple(
            entry for entry in filtered.entries if isinstance(entry, Event)
        )
        g.ledger.set_report_view_cache("event_rows", rows_key, all_events)

    event_type_counts: Sequence[EventTypeCount] | None = None
    serialized_chart_events: Sequence[object] | None = None
    chart_event_count: int | None = None
    sampled: bool | None = None
    if include_overview:
        chart_key = (filtered, revision)
        cached_event_overview = cast(
            "EventOverview | None",
            g.ledger.get_report_view_cache("event_overview", chart_key),
        )
        if cached_event_overview is None:
            chart_events = tuple(
                sorted(all_events, key=lambda entry: entry.date)
            )
            counts = Counter(event.type for event in chart_events)
            event_type_counts = tuple(
                EventTypeCount(type=name, count=count)
                for name, count in sorted(counts.items())
            )
            sample = _sample_events(chart_events)
            serialized_chart_events = tuple(
                serialise(event) for event in sample
            )
            cached_event_overview = (
                chart_events,
                event_type_counts,
                serialized_chart_events,
            )
            g.ledger.set_report_view_cache(
                "event_overview", chart_key, cached_event_overview
            )
        chart_events, event_type_counts, serialized_chart_events = (
            cached_event_overview
        )
        chart_event_count = len(chart_events)
        sampled = len(chart_events) > len(serialized_chart_events)

    table_key = (filtered, revision, sort, order)
    events = cast(
        "Sequence[Event] | None",
        g.ledger.get_report_view_cache("events", table_key),
    )
    if events is None:
        if sort == "date":
            events = tuple(
                sorted(
                    all_events,
                    key=lambda entry: entry.date,
                    reverse=order == "desc",
                )
            )
        elif sort == "description":
            events = tuple(
                sorted(
                    all_events,
                    key=lambda entry: entry.description.casefold(),
                    reverse=order == "desc",
                )
            )
        else:
            events = tuple(
                sorted(
                    all_events,
                    key=lambda entry: entry.type.casefold(),
                    reverse=order == "desc",
                )
            )
        g.ledger.set_report_view_cache("events", table_key, events)

    subset_key = (filtered, revision, event_type or "", sort, order)
    selected_events = cast(
        "Sequence[Event] | None",
        g.ledger.get_report_view_cache("event_subsets", subset_key),
    )
    if selected_events is None:
        selected_events = (
            events
            if event_type is None or event_type == ""
            else tuple(event for event in events if event.type == event_type)
        )
        g.ledger.set_report_view_cache(
            "event_subsets", subset_key, selected_events
        )
    total_entries = len(selected_events)
    start, total_pages = _report_page_slice(page, per_page, total_entries)
    page_events = selected_events[start : start + per_page]
    return EventPage(
        events=[serialise(event) for event in page_events],
        page=page,
        page_size=per_page,
        total_entries=total_entries,
        total_pages=total_pages,
        revision=str(revision),
        types=event_type_counts,
        chart_events=serialized_chart_events,
        total_events=chart_event_count,
        chart_events_sampled=sampled,
        chart_total_events=chart_event_count,
    )


@api_endpoint
def get_imports() -> Sequence[FileImporters]:
    """Get a list of the importable files."""
    g.ledger.changed()
    return g.ledger.ingest.import_data()


@api_endpoint
def get_documents() -> Sequence[object]:
    """Get all (filtered) documents."""
    g.ledger.changed()
    return [
        serialise(e) for e in g.filtered.entries if isinstance(e, Document)
    ]


@api_endpoint
def get_documents_page(
    page: int = 1,
    per_page: int = 200,
    sort: str = "date",
    order: str = "desc",
    a: str | None = None,
    include_overview: bool = True,  # noqa: FBT001, FBT002
) -> DocumentPage:
    """Get a bounded page of documents with account totals."""
    _validate_report_sort(sort, ("date", "name"))
    _validate_report_order(order)
    _validate_report_page(page, per_page)
    g.ledger.changed()

    filtered = g.filtered
    revision = filtered.revision
    cache_key = (filtered, revision, sort, order)
    cached_documents = cast(
        "tuple[Sequence[Document], Sequence[AccountDocumentCount]] | None",
        g.ledger.get_report_view_cache("documents", cache_key),
    )
    if cached_documents is None:
        unsorted_documents = [
            entry for entry in filtered.entries if isinstance(entry, Document)
        ]

        def document_name(entry: Document) -> str:
            filename = Path(entry.filename).name
            if filename.startswith(entry.date.isoformat()):
                filename = filename[11:]
            return filename.casefold()

        sort_key = (
            (lambda entry: entry.date) if sort == "date" else document_name
        )
        documents = tuple(
            sorted(
                unsorted_documents,
                key=sort_key,
                reverse=order == "desc",
            )
        )
        account_counts = Counter(document.account for document in documents)
        accounts = tuple(
            AccountDocumentCount(account=account, count=count)
            for account, count in sorted(account_counts.items())
        )
        cached_documents = (documents, accounts)
        g.ledger.set_report_view_cache(
            "documents", cache_key, cached_documents
        )
    documents, accounts = cached_documents
    subset_key = (filtered, revision, a or "", sort, order)
    selected_documents = cast(
        "Sequence[Document] | None",
        g.ledger.get_report_view_cache("document_subsets", subset_key),
    )
    if selected_documents is None:
        if a:
            is_selected_account = account_tester(a, with_children=True)
            selected_documents = tuple(
                document
                for document in documents
                if is_selected_account(document.account)
            )
        else:
            selected_documents = documents
        g.ledger.set_report_view_cache(
            "document_subsets", subset_key, selected_documents
        )
    total_entries = len(selected_documents)
    start, total_pages = _report_page_slice(page, per_page, total_entries)
    page_documents = selected_documents[start : start + per_page]
    return DocumentPage(
        documents=[serialise(document) for document in page_documents],
        page=page,
        page_size=per_page,
        total_entries=total_entries,
        total_pages=total_pages,
        revision=str(revision),
        accounts=accounts if include_overview else None,
    )


class Options(Struct, frozen=True):
    """Fava and Beancount options as strings."""

    fava_options: Mapping[str, str]
    beancount_options: Mapping[str, str]


@api_endpoint
def get_options() -> Options:
    """Get all options, rendered to strings for displaying in the frontend."""
    g.ledger.changed()

    fava_options = g.ledger.fava_options
    pprinted_fava_options = {
        name.replace("_", "-"): pformat(getattr(fava_options, name))
        for name in All_OPTS
    }
    return Options(
        pprinted_fava_options,
        {key: str(value) for key, value in g.ledger.options.items()},
    )


class HelpPage(Struct, frozen=True):
    """A rendered help page and the list of all help pages."""

    html: str
    pages: Sequence[tuple[str, str]]


@api_endpoint
def get_help(page_slug: str) -> HelpPage:
    """Get one of Fava's help pages, rendered to HTML."""
    from fava.help import HELP_PAGES
    from fava.help import render_help_page

    html = render_help_page(page_slug)
    if html is None:
        raise NotFoundError
    return HelpPage(html, list(HELP_PAGES.items()))


class CommodityPairWithPrices(Struct, frozen=True):
    """A pair of commodities and prices for them."""

    base: str
    quote: str
    prices: Sequence[tuple[date, Decimal]]


@api_endpoint
def get_commodities() -> Sequence[CommodityPairWithPrices]:
    """Get the prices for all commodity pairs."""
    g.ledger.changed()
    ret = []
    for base, quote in g.ledger.commodity_pairs():
        prices = g.filtered.prices(base, quote)
        if prices:
            ret.append(CommodityPairWithPrices(base, quote, prices))

    return ret


def _commodity_pair_counts(
    filtered: FilteredLedger,
    revision: int,
    pairs: Sequence[tuple[str, str]],
) -> Sequence[CommodityPairCount]:
    """Get cached price point counts for each commodity pair."""
    cache_key = (filtered, revision)
    cached = cast(
        "Sequence[CommodityPairCount] | None",
        g.ledger.get_report_view_cache("commodity_pairs", cache_key),
    )
    if cached is not None:
        return cached

    counts = tuple(
        CommodityPairCount(
            base=base,
            quote=quote,
            count=len(filtered.prices(base, quote)),
        )
        for base, quote in pairs
    )
    g.ledger.set_report_view_cache("commodity_pairs", cache_key, counts)
    return counts


def _commodity_price_views(
    filtered: FilteredLedger,
    revision: int,
    base: str,
    quote: str,
    sort: str,
    order: str,
) -> tuple[Sequence[tuple[date, Decimal]], Sequence[tuple[date, Decimal]]]:
    """Get cached chronological and requested-order price views."""
    canonical_key = (filtered, revision, base, quote, "date", "asc")
    pair_prices = cast(
        "Sequence[tuple[date, Decimal]] | None",
        g.ledger.get_report_view_cache("commodities", canonical_key),
    )
    if pair_prices is None:
        pair_prices = tuple(filtered.prices(base, quote))
        g.ledger.set_report_view_cache(
            "commodities", canonical_key, pair_prices
        )

    requested_key = (filtered, revision, base, quote, sort, order)
    ordered_prices = cast(
        "Sequence[tuple[date, Decimal]] | None",
        g.ledger.get_report_view_cache("commodities", requested_key),
    )
    if ordered_prices is not None:
        return pair_prices, ordered_prices

    ordered_prices = tuple(
        sorted(
            pair_prices,
            key=(lambda point: point[0])
            if sort == "date"
            else (lambda point: point[1]),
            reverse=order == "desc",
        )
    )
    g.ledger.set_report_view_cache(
        "commodities", requested_key, ordered_prices
    )
    return pair_prices, ordered_prices


@api_endpoint
def get_commodity_report(
    base: str | None = None,
    quote: str | None = None,
    page: int = 1,
    per_page: int = 200,
    sort: str = "date",
    order: str = "desc",
    include_overview: bool = True,  # noqa: FBT001, FBT002
) -> CommodityPricePage:
    """Get one pair's prices in bounded pages with a chart overview."""
    if (base is None) != (quote is None):
        detail = "base and quote must be provided together"
        raise _report_validation_error(detail)
    _validate_report_sort(sort, ("date", "price"))
    _validate_report_order(order)
    _validate_report_page(page, per_page)
    g.ledger.changed()

    filtered = g.filtered
    revision = filtered.revision
    commodity_pairs = g.ledger.commodity_pairs()
    if (
        base is not None
        and quote is not None
        and (base, quote) not in commodity_pairs
    ):
        detail = f"unknown commodity pair: {base}/{quote}"
        raise _report_validation_error(detail)

    pair_counts = _commodity_pair_counts(filtered, revision, commodity_pairs)
    visible_pairs = [pair for pair in pair_counts if pair.count]
    if base is None or quote is None:
        if visible_pairs:
            base = visible_pairs[0].base
            quote = visible_pairs[0].quote
        else:
            base = quote = ""

    if base and quote:
        pair_prices, ordered_prices = _commodity_price_views(
            filtered, revision, base, quote, sort, order
        )
    else:
        pair_prices = ()
        ordered_prices = ()

    total_entries = len(ordered_prices)
    start, total_pages = _report_page_slice(page, per_page, total_entries)
    page_prices = ordered_prices[start : start + per_page]
    chart_prices = (
        _sample_sequence(pair_prices, _MAX_REPORT_CHART_POINTS)
        if include_overview
        else None
    )
    chart_prices_sampled = (
        len(pair_prices) > len(chart_prices)
        if chart_prices is not None
        else None
    )
    return CommodityPricePage(
        pairs=visible_pairs if include_overview else None,
        base=base,
        quote=quote,
        prices=page_prices,
        chart_prices=chart_prices,
        page=page,
        page_size=per_page,
        total_entries=total_entries,
        total_pages=total_pages,
        revision=str(revision),
        chart_prices_sampled=chart_prices_sampled,
        chart_total_prices=len(pair_prices) if include_overview else None,
    )


class TreeReport(Struct, frozen=True):
    """Data for the tree reports."""

    date_range: DateRange | None
    charts: Sequence[ChartData]
    trees: Sequence[SerialisedTreeNode]


@api_endpoint
def get_income_statement() -> TreeReport:
    """Get the data for the income statement."""
    g.ledger.changed()
    options = g.ledger.options
    invert = g.ledger.fava_options.invert_income_liabilities_equity

    charts = [
        ChartApi.interval_totals(
            g.interval,
            (options["name_income"], options["name_expenses"]),
            label=gettext("Net Profit"),
            invert=invert,
        ),
        ChartApi.interval_totals(
            g.interval,
            options["name_income"],
            label=f"{gettext('Income')} ({g.interval.label})",
            invert=invert,
        ),
        ChartApi.interval_totals(
            g.interval,
            options["name_expenses"],
            label=f"{gettext('Expenses')} ({g.interval.label})",
        ),
    ]
    root_tree = g.filtered.root_tree
    trees = [
        root_tree.get(options["name_income"]),
        root_tree.net_profit(options, gettext("Net Profit")),
        root_tree.get(options["name_expenses"]),
    ]

    return TreeReport(
        g.filtered.date_range,
        charts,
        trees=[tree.serialise_with_context() for tree in trees],
    )


@api_endpoint
def get_balance_sheet() -> TreeReport:
    """Get the data for the balance sheet."""
    g.ledger.changed()
    options = g.ledger.options

    charts = [ChartApi.net_worth()]
    root_tree_closed = g.filtered.root_tree_closed
    trees = [
        root_tree_closed.get(options["name_assets"]),
        root_tree_closed.get(options["name_liabilities"]),
        root_tree_closed.get(options["name_equity"]),
    ]

    return TreeReport(
        g.filtered.date_range,
        charts,
        trees=[tree.serialise_with_context() for tree in trees],
    )


@api_endpoint
def get_trial_balance() -> TreeReport:
    """Get the data for the trial balance."""
    g.ledger.changed()

    trees = [g.filtered.root_tree.get("")]

    return TreeReport(
        g.filtered.date_range,
        charts=[],
        trees=[tree.serialise_with_context() for tree in trees],
    )


class AccountBudget(Struct, frozen=True):
    """Budgets for an account."""

    budget: Mapping[str, Decimal]
    budget_children: Mapping[str, Decimal]


class AccountReportJournal(Struct, frozen=True):
    """Data for the journal account report."""

    charts: Sequence[ChartData]
    journal: str


class AccountReportTree(Struct, frozen=True):
    """Data for the tree account reports."""

    charts: Sequence[ChartData]
    interval_balances: Sequence[SerialisedTreeNode]
    budgets: Mapping[str, Sequence[AccountBudget]]
    dates: Sequence[DateRange]


@api_endpoint
def get_account_report(
    a: str = "",
    r: str = "",
    include_journal: bool = True,  # noqa: FBT001, FBT002
) -> AccountReportJournal | AccountReportTree:
    """Get the data for the account report."""
    g.ledger.changed()

    charts = [
        ChartApi.account_balance(a),
        ChartApi.interval_totals(
            g.interval,
            a,
            label=gettext("Changes"),
        ),
    ]

    if r in {"changes", "balances"}:
        accumulate = r == "balances"
        interval_balances, dates = g.ledger.interval_balances(
            g.filtered, g.interval, a, accumulate=accumulate
        )
        if not dates:
            return AccountReportTree(
                charts, interval_balances=[], budgets={}, dates=[]
            )

        all_accounts = (
            interval_balances[0].accounts if interval_balances else []
        )
        is_child_account = account_tester(a, with_children=True)
        budget_accounts = [
            acc for acc in all_accounts if is_child_account(acc)
        ]
        budgets_mod = g.ledger.budgets
        first_date_range = dates[-1]
        budgets = {
            account: [
                AccountBudget(
                    budgets_mod.calculate(
                        account,
                        (first_date_range if accumulate else date_range).begin,
                        date_range.end,
                    ),
                    budgets_mod.calculate_children(
                        account,
                        (first_date_range if accumulate else date_range).begin,
                        date_range.end,
                    ),
                )
                for date_range in dates
            ]
            for account in budget_accounts
        }

        return AccountReportTree(
            charts,
            interval_balances=[
                tree.get(a).serialise(
                    g.conv,
                    g.ledger.prices,
                    date_range.end_inclusive,
                    with_cost=False,
                )
                for tree, date_range in zip(
                    interval_balances, dates, strict=True
                )
            ],
            dates=dates,
            budgets=budgets,
        )

    if not include_journal:
        return AccountReportJournal(charts, journal="")

    journal_table_contents = get_template_attribute(
        "_journal_table.html", "journal_table_contents"
    )
    entries = reversed(
        g.ledger.account_journal(
            g.filtered,
            a,
            g.conversion,
            with_children=g.ledger.fava_options.account_journal_include_children,
        )
    )
    return AccountReportJournal(
        charts,
        journal=journal_table_contents(entries, show_change_and_balance=True),
    )


class Statistics(Struct, frozen=True):
    """Data for the statistics report."""

    all_balance_directives: str
    balances: Mapping[str, SimpleCounterInventory]
    entries_by_type: Mapping[str, int]


@api_endpoint
def get_statistics() -> Statistics:
    """Get the data for the statistics report."""
    g.ledger.changed()

    entries_by_type = group_entries_by_type(g.filtered.entries).count_by_type()

    balances = {
        account_name: UNITS.apply(node.balance)
        for account_name, node in g.filtered.root_tree.items()
    }

    return Statistics(
        all_balance_directives=g.ledger.accounts.all_balance_directives(),
        balances=balances,
        entries_by_type=entries_by_type,
    )
