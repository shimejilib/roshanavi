"""data_dir access: path containment, file listing and stream-file parsing.

Every user-supplied path is resolved with ``os.path.realpath`` and must stay
inside the realpath of ``data_dir`` (blocks ``..`` traversal, absolute paths
and symlinks pointing outside).
"""

import csv
import json
import logging
import os
from typing import Any, Dict, List

from .media.kinds import IMAGE_DEMUXERS, media_kind

LOG = logging.getLogger(__name__)

MAX_STREAM_BYTES = 50 * 1024 * 1024
MAX_STREAM_RECORDS = 100000
MAX_LISTED_FILES = 1000
MAX_LIST_DEPTH = 6
BAG_FILE_EXTS = ('.mcap', '.db3')


class FileAccessError(ValueError):
    """``code`` is one of: forbidden_path, not_found, invalid_file."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def resolve_in_data_dir(data_dir: str, user_path: str) -> str:
    """Return the realpath of ``user_path`` if it lies inside ``data_dir``."""
    if not isinstance(user_path, str) or not user_path or '\x00' in user_path:
        raise FileAccessError('forbidden_path', 'path must be a non-empty string')
    root = os.path.realpath(data_dir)
    candidate = os.path.realpath(os.path.join(root, user_path))
    if os.path.commonpath([root, candidate]) != root:
        raise FileAccessError('forbidden_path', f'path escapes data_dir: {user_path}')
    if not os.path.exists(candidate):
        raise FileAccessError('not_found', f'no such file in data_dir: {user_path}')
    return candidate


def _kind(path: str, is_dir: bool) -> str:
    if is_dir:
        return 'bag'
    lower = path.lower()
    if lower.endswith('.jsonl'):
        return 'jsonl'
    if lower.endswith('.csv'):
        return 'csv'
    if lower.endswith(BAG_FILE_EXTS):
        return 'bag'
    return media_kind(path) or 'other'


def list_files(data_dir: str) -> List[Dict[str, Any]]:
    """Files under ``data_dir`` (bag directories are reported as one entry)."""
    root = os.path.realpath(data_dir)
    if not os.path.isdir(root):
        return []
    result: List[Dict[str, Any]] = []
    for current, dirs, files in os.walk(root, followlinks=False):
        rel_dir = os.path.relpath(current, root)
        depth = 0 if rel_dir == '.' else rel_dir.count(os.sep) + 1
        if 'metadata.yaml' in files and current != root:
            result.append({'path': rel_dir, 'size': _dir_size(current), 'kind': 'bag'})
            dirs[:] = []
            continue
        if depth >= MAX_LIST_DEPTH:
            dirs[:] = []
        dirs.sort()
        if current != root and any(os.path.splitext(n)[1].lower() in IMAGE_DEMUXERS
                                   for n in files):
            result.append({'path': rel_dir, 'size': _dir_size(current), 'kind': 'image_dir'})
        for name in sorted(files):
            full = os.path.join(current, name)
            rel = os.path.relpath(full, root)
            try:
                size = os.path.getsize(full)
            except OSError as exc:
                LOG.warning('cannot stat %s: %s', full, exc)
                continue
            result.append({'path': rel, 'size': size, 'kind': _kind(name, False)})
            if len(result) >= MAX_LISTED_FILES:
                return result
    return result


def _dir_size(path: str) -> int:
    total = 0
    for current, _, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(current, name))
            except OSError as exc:
                LOG.warning('cannot stat %s: %s', name, exc)
    return total


def load_stream(path: str) -> List[Dict[str, Any]]:
    """Parse a JSONL or CSV stream file into a list of message dicts."""
    size = os.path.getsize(path)
    if size > MAX_STREAM_BYTES:
        raise FileAccessError('invalid_file', f'stream file larger than {MAX_STREAM_BYTES} bytes')
    lower = path.lower()
    with open(path, encoding='utf-8', newline='') as fh:
        text = fh.read()
    if lower.endswith('.jsonl') or lower.endswith('.ndjson'):
        records = parse_jsonl(text)
    elif lower.endswith('.csv'):
        records = parse_csv(text)
    else:
        raise FileAccessError('invalid_file', 'stream file must be .jsonl or .csv')
    if not records:
        raise FileAccessError('invalid_file', 'stream file contains no records')
    return records


def parse_jsonl(text: str) -> List[Dict[str, Any]]:
    records = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise FileAccessError('invalid_file',
                                  f'line {lineno}: invalid JSON: {exc.msg}') from exc
        if not isinstance(record, dict):
            raise FileAccessError('invalid_file', f'line {lineno}: expected a JSON object')
        records.append(record)
        if len(records) > MAX_STREAM_RECORDS:
            raise FileAccessError('invalid_file', f'more than {MAX_STREAM_RECORDS} records')
    return records


def parse_csv(text: str) -> List[Dict[str, Any]]:
    """Header row = dotted field paths (``a.b.c``); cells parsed as JSON scalars if possible."""
    reader = csv.reader(text.splitlines())
    try:
        header = next(reader)
    except StopIteration:
        return []
    paths = [h.strip() for h in header]
    if not all(paths) or len(set(paths)) != len(paths):
        raise FileAccessError('invalid_file', 'CSV header must contain unique, non-empty paths')
    records = []
    for lineno, row in enumerate(reader, start=2):
        if not any(cell.strip() for cell in row):
            continue
        if len(row) != len(paths):
            raise FileAccessError('invalid_file',
                                  f'line {lineno}: expected {len(paths)} columns, got {len(row)}')
        record: Dict[str, Any] = {}
        for field_path, cell in zip(paths, row):
            _set_path(record, field_path.split('.'), _parse_cell(cell), lineno)
        records.append(record)
        if len(records) > MAX_STREAM_RECORDS:
            raise FileAccessError('invalid_file', f'more than {MAX_STREAM_RECORDS} records')
    return records


def _parse_cell(cell: str) -> Any:
    stripped = cell.strip()
    if stripped in ('true', 'false'):
        return stripped == 'true'
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        return cell
    return value if isinstance(value, (int, float, list)) else cell


def _set_path(record: Dict[str, Any], parts: List[str], value: Any, lineno: int) -> None:
    node = record
    for part in parts[:-1]:
        child = node.setdefault(part, {})
        if not isinstance(child, dict):
            raise FileAccessError('invalid_file', f'line {lineno}: conflicting path at {part}')
        node = child
    node[parts[-1]] = value
