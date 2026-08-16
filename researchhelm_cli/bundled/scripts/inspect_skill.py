"""Inspect an already-fetched Agent Skill directory without executing its content."""

from __future__ import annotations

import argparse
import base64
import ctypes
import errno
import hashlib
import importlib.util
import json
import os
import re
import stat
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Callable
from urllib.parse import unquote, urlsplit


EXECUTABLE_SUFFIXES = {".bat", ".cmd", ".exe", ".js", ".mjs", ".ps1", ".py", ".sh"}
MAX_INSPECTED_BYTES = 1_048_576
MAX_FILES = 4096
MAX_DEPTH = 32
MAX_TOTAL_BYTES = 268_435_456
_NAME_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{0,63}\Z")
_KEY_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_-]*\Z")
_IMMUTABLE_REVISION = re.compile(r"[0-9a-fA-F]{6,64}\Z")
_PATH_SLASH = chr(47)
_WINDOWS_LOCAL_PATH = re.compile(
    rf"(?i)(?:(?:^|[{_PATH_SLASH}\s])[A-Z]:[\\{_PATH_SLASH}]|"
    rf"\\\\|{_PATH_SLASH}(?:home|Users){_PATH_SLASH})"
)
_BASE64_CANDIDATE = re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{24,}={0,2}(?![A-Za-z0-9+/=])")
_WINDOWS_DEVICE_NAME = re.compile(
    r"(?i)(?:CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|COM[1-9¹²³]|LPT[1-9¹²³])(?:\..*)?\Z"
)
_BLOCKING_RISKS = {
    "hardlink",
    "identity_changed",
    "inspection_failed",
    "invalid_root",
    "large_file",
    "resource_limit_bytes",
    "resource_limit_depth",
    "resource_limit_files",
    "sensitive_content",
    "sensitive_path",
    "symlink",
    "unsafe_revision",
    "unsafe_root",
    "unsafe_source",
    "unsupported_entry",
    "unsupported_secure_traversal",
}
_SECURITY_MODULE: Any | None = None

_FILE_ATTRIBUTE_DIRECTORY = 0x10
_FILE_ATTRIBUTE_DEVICE = 0x40
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
_GENERIC_READ = 0x80000000
_FILE_SHARE_READ = 0x1
_OPEN_EXISTING = 3
_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_DRIVE_REMOTE = 4

_SYS_OPENAT2 = 437
_RESOLVE_NO_XDEV = 0x01
_RESOLVE_NO_MAGICLINKS = 0x02
_RESOLVE_NO_SYMLINKS = 0x04
_RESOLVE_BENEATH = 0x08
_OPENAT2_RESOLVE = (
    _RESOLVE_NO_XDEV | _RESOLVE_NO_MAGICLINKS | _RESOLVE_NO_SYMLINKS | _RESOLVE_BENEATH
)
_OPENAT2_MACHINES = {
    "aarch64",
    "arm64",
    "i386",
    "i686",
    "riscv64",
    "s390x",
    "x86_64",
}


class _FILETIME(ctypes.Structure):
    _fields_ = [("low", ctypes.c_uint32), ("high", ctypes.c_uint32)]


class _BY_HANDLE_FILE_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("attributes", ctypes.c_uint32),
        ("creation_time", _FILETIME),
        ("access_time", _FILETIME),
        ("write_time", _FILETIME),
        ("volume_serial", ctypes.c_uint32),
        ("size_high", ctypes.c_uint32),
        ("size_low", ctypes.c_uint32),
        ("number_of_links", ctypes.c_uint32),
        ("file_index_high", ctypes.c_uint32),
        ("file_index_low", ctypes.c_uint32),
    ]


class _OPEN_HOW(ctypes.Structure):
    _fields_ = [
        ("flags", ctypes.c_uint64),
        ("mode", ctypes.c_uint64),
        ("resolve", ctypes.c_uint64),
    ]


class UnsafeEntryError(OSError):
    """A content-free signal that an entry cannot be inspected safely."""

    def __init__(self, code: str = "inspection_failed") -> None:
        super().__init__(code)
        self.code = code


class ResourceLimitError(UnsafeEntryError):
    pass


def _tree_hash(files: list[dict[str, Any]]) -> str:
    payload = json.dumps(files, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _empty_report(
    source: str | None,
    revision: str | None,
    risks: list[dict[str, str]],
) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    return {
        "valid_skill": False,
        "frontmatter": {},
        "files": files,
        "tree_hash": _tree_hash(files),
        "risks": _risk_records(risks),
        "source": source,
        "revision": revision,
    }


def _load_security_module() -> Any:
    global _SECURITY_MODULE
    if _SECURITY_MODULE is None:
        path = Path(__file__).with_name("sanitize_export.py")
        name = "_researchhelm_inspection_security"
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise UnsafeEntryError()
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        _SECURITY_MODULE = module
    return _SECURITY_MODULE


def _contains_sensitive_text(text: str) -> bool:
    try:
        return bool(_load_security_module().scan_text(text, "state"))
    except Exception as error:
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            raise
        raise UnsafeEntryError() from None


def _decoded_texts(payload: bytes) -> list[str]:
    texts = [payload.decode("utf-8", errors="ignore")]
    if payload.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            texts.append(payload.decode("utf-16"))
        except UnicodeDecodeError:
            pass
    elif len(payload) >= 8:
        pairs = len(payload) // 2
        even_nulls = payload[0::2].count(0)
        odd_nulls = payload[1::2].count(0)
        encoding = None
        if odd_nulls > pairs // 3:
            encoding = "utf-16-le"
        elif even_nulls > pairs // 3:
            encoding = "utf-16-be"
        if encoding:
            try:
                texts.append(payload.decode(encoding))
            except UnicodeDecodeError:
                pass
    return texts


def _text_variants(payload: bytes) -> list[str]:
    variants = _decoded_texts(payload)
    for text in tuple(variants):
        if "%" in text:
            variants.append(unquote(text))
        for match in _BASE64_CANDIDATE.finditer(text):
            candidate = match.group()
            if len(candidate) % 4:
                continue
            try:
                decoded = base64.b64decode(candidate, validate=True)
            except (ValueError, TypeError):
                continue
            if len(decoded) <= MAX_INSPECTED_BYTES:
                variants.extend(_decoded_texts(decoded))
    return variants


def _contains_sensitive_payload(payload: bytes) -> bool:
    return any(_contains_sensitive_text(text) for text in _text_variants(payload))


def _sanitize_metadata(
    source: str | None, revision: str | None
) -> tuple[str | None, str | None, list[dict[str, str]]]:
    risks: list[dict[str, str]] = []
    safe_source: str | None = None
    if source is not None:
        try:
            parsed = urlsplit(source)
            source_is_safe = bool(
                isinstance(source, str)
                and "%" not in source
                and parsed.scheme == "https"
                and parsed.hostname
                and parsed.username is None
                and parsed.password is None
                and not parsed.query
                and not parsed.fragment
                and not any(character.isspace() or ord(character) < 32 for character in source)
                and not _WINDOWS_LOCAL_PATH.search(source)
                and not _contains_sensitive_text(source)
            )
            parsed.port
        except (TypeError, ValueError, UnsafeEntryError):
            source_is_safe = False
        if source_is_safe:
            safe_source = source
        else:
            risks.append({"code": "unsafe_source", "path": "source"})

    safe_revision: str | None = None
    if revision is not None:
        try:
            revision_is_safe = bool(
                isinstance(revision, str)
                and _IMMUTABLE_REVISION.fullmatch(revision)
                and not _contains_sensitive_text(revision)
            )
        except UnsafeEntryError:
            revision_is_safe = False
        if revision_is_safe:
            safe_revision = revision
        else:
            risks.append({"code": "unsafe_revision", "path": "revision"})
    return safe_source, safe_revision, risks


def _simple_scalar(value: str) -> str | None:
    value = value.strip()
    if not value or value in {">", "|"}:
        return None
    if value[0] in "[{&*!@`":
        return None
    if value[0] in "\"'":
        if len(value) < 2 or value[-1] != value[0]:
            return None
        return value[1:-1]
    return value


def parse_simple_frontmatter(text: str) -> tuple[dict[str, str], bool]:
    """Parse only a conservative, flat YAML subset and report verification status."""

    lines = text.replace("\r\n", "\n").splitlines()
    if not lines or lines[0] != "---":
        return {}, False
    try:
        closing = lines.index("---", 1)
    except ValueError:
        return {}, False
    if closing == 1:
        return {}, False
    result: dict[str, str] = {}
    for line in lines[1:closing]:
        if not line or line.startswith((" ", "\t", "#")) or ":" not in line:
            return {}, False
        key, raw_value = line.split(":", 1)
        key = key.strip()
        value = _simple_scalar(raw_value)
        if not _KEY_PATTERN.fullmatch(key) or key in result or value is None:
            return {}, False
        result[key] = value
    return result, True


def _reject_unsafe_root_spelling(raw: str) -> None:
    if not raw or "\x00" in raw:
        raise UnsafeEntryError("unsafe_root")
    windows = raw.replace("/", "\\")
    if windows.startswith("\\\\"):
        raise UnsafeEntryError("unsafe_root")
    windows_path = PureWindowsPath(raw)
    if windows_path.drive and not windows_path.root:
        raise UnsafeEntryError("unsafe_root")
    for component in windows_path.parts:
        if component == windows_path.anchor:
            continue
        if (
            ":" in component
            or component.endswith((" ", "."))
            or _WINDOWS_DEVICE_NAME.fullmatch(component)
        ):
            raise UnsafeEntryError("unsafe_root")
    if ".." in windows_path.parts or ".." in PurePosixPath(raw).parts:
        raise UnsafeEntryError("unsafe_root")


def _prepare_root_path(root: os.PathLike[str] | str) -> Path:
    raw = os.fspath(root)
    _reject_unsafe_root_spelling(raw)
    absolute = os.path.abspath(os.path.normpath(raw))
    _reject_unsafe_root_spelling(absolute)
    return Path(absolute)


def _safe_relative_path(relative: str) -> bool:
    if (
        not relative
        or relative.startswith(("/", "\\"))
        or ".." in PurePosixPath(relative).parts
        or any(ord(character) < 32 for character in relative)
    ):
        return False
    try:
        candidates = (relative, *PurePosixPath(relative).parts)
        return not any(
            _contains_sensitive_payload(candidate.encode("utf-8"))
            for candidate in candidates
        )
    except UnsafeEntryError:
        return False


def _safe_entry_name(name: str) -> bool:
    if not name or name in {".", ".."} or any(
        character in name for character in ("/", "\\", "\x00")
    ):
        return False
    if os.name == "nt" and (
        ":" in name or name.endswith((" ", ".")) or _WINDOWS_DEVICE_NAME.fullmatch(name)
    ):
        return False
    return True


def _executable_status(relative: str, mode: int, prefix: bytes) -> bool:
    suffix = PurePosixPath(relative).suffix.lower()
    return bool(
        suffix in EXECUTABLE_SUFFIXES
        or mode & 0o111
        or (not suffix and prefix.startswith(b"#!"))
    )


def _risk_records(risks: list[dict[str, str]]) -> list[dict[str, str]]:
    pairs = sorted({(item["code"], item["path"]) for item in risks}, key=lambda item: (item[1], item[0]))
    return [{"code": code, "path": path} for code, path in pairs]


def _new_state(risks: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "files": [],
        "risks": risks,
        "skill_payload": None,
        "file_count": 0,
        "unsafe_count": 0,
        "total_bytes": 0,
        "open_count": 0,
        "windows_directories": [],
        "windows_files": [],
        "windows_handles": [],
        "windows_fds": [],
        "posix_directories": [],
        "posix_files": [],
        "posix_fds": [],
    }


def _unsafe_location(state: dict[str, Any]) -> str:
    state["unsafe_count"] += 1
    return f"entry={state['unsafe_count']}"


def _bounded_names(entries: Any, limit: int) -> tuple[tuple[str, ...], bool]:
    names: list[str] = []
    for entry in entries:
        if len(names) >= limit:
            return tuple(names), True
        names.append(entry.name)
    return tuple(names), False


def _initial_names(entries: Any, state: dict[str, Any]) -> tuple[str, ...]:
    names, overflow = _bounded_names(entries, MAX_FILES - state["file_count"])
    if overflow:
        raise ResourceLimitError("resource_limit_files")
    return tuple(sorted(names))


def _reserve_entry(state: dict[str, Any]) -> None:
    state["file_count"] += 1
    if state["file_count"] > MAX_FILES:
        raise ResourceLimitError("resource_limit_files")


def _reserve_handle(state: dict[str, Any]) -> None:
    if state["open_count"] >= MAX_FILES:
        raise ResourceLimitError("resource_limit_files")
    state["open_count"] += 1


def _release_handle(state: dict[str, Any]) -> None:
    state["open_count"] -= 1


def _append_resource(resources: Any, resource: int) -> None:
    resources.append(resource)


def _register_open_resource(
    resources: Any,
    resource: int,
    closer: Callable[[int], None],
    state: dict[str, Any] | None = None,
) -> None:
    try:
        _append_resource(resources, resource)
    except BaseException:
        try:
            closer(resource)
        except OSError:
            pass
        finally:
            if state is not None:
                _release_handle(state)
        raise


def _reserve_bytes(state: dict[str, Any], size: int) -> None:
    if size < 0 or state["total_bytes"] + size > MAX_TOTAL_BYTES:
        raise ResourceLimitError("resource_limit_bytes")
    state["total_bytes"] += size


def _placeholder(path: str, kind: str) -> dict[str, Any]:
    return {"path": path, "size": None, "sha256": None, "mode": None, "executable": False, "kind": kind}


def _read_open_file(
    descriptor: int,
    size: int,
    relative: str,
    mode: int,
    stable_after_read: Callable[[], bool],
) -> tuple[dict[str, Any], bytes | None, list[str]]:
    large = size > MAX_INSPECTED_BYTES
    limit = 4096 if large else MAX_INSPECTED_BYTES + 1
    chunks: list[bytes] = []
    total = 0
    while total < limit:
        chunk = os.read(descriptor, min(65_536, limit - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
    if not stable_after_read():
        raise UnsafeEntryError("identity_changed")
    payload = b"".join(chunks)
    if not large and total != size:
        raise UnsafeEntryError("identity_changed")

    sensitive = _contains_sensitive_payload(payload)
    prefix = payload[:4096]
    executable = _executable_status(relative, mode, b"" if sensitive else prefix)
    digest = None if large or sensitive else hashlib.sha256(payload).hexdigest()
    record = {
        "path": relative,
        "size": None if sensitive else size,
        "sha256": digest,
        "mode": mode,
        "executable": executable,
        "kind": "file",
    }
    codes: list[str] = []
    if large:
        codes.append("large_file")
    if sensitive:
        codes.append("sensitive_content")
    if executable:
        codes.append("executable_content")
    if not sensitive and b"\x00" in prefix:
        codes.append("binary_content")
    retained = payload if relative == "SKILL.md" and not large and not sensitive else None
    return record, retained, codes


def _windows_kernel32() -> Any:
    if os.name != "nt":
        raise UnsafeEntryError("unsupported_secure_traversal")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.restype = ctypes.c_void_p
    kernel32.CreateFileW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    kernel32.GetFileInformationByHandle.restype = ctypes.c_int
    kernel32.GetFileInformationByHandle.argtypes = [ctypes.c_void_p, ctypes.POINTER(_BY_HANDLE_FILE_INFORMATION)]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    return kernel32


def _windows_drive_type(anchor: str) -> int:
    kernel32 = _windows_kernel32()
    kernel32.GetDriveTypeW.restype = ctypes.c_uint32
    kernel32.GetDriveTypeW.argtypes = [ctypes.c_wchar_p]
    return int(kernel32.GetDriveTypeW(anchor))


def _windows_open_handle(path: Path) -> int:
    kernel32 = _windows_kernel32()
    handle = kernel32.CreateFileW(
        os.fspath(path),
        _GENERIC_READ,
        _FILE_SHARE_READ,
        None,
        _OPEN_EXISTING,
        _FILE_FLAG_BACKUP_SEMANTICS | _FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    if handle in (None, ctypes.c_void_p(-1).value):
        raise UnsafeEntryError()
    return int(handle)


def _windows_close_handle(handle: int) -> None:
    _windows_kernel32().CloseHandle(ctypes.c_void_p(handle))


def _windows_info(handle: int) -> dict[str, int]:
    info = _BY_HANDLE_FILE_INFORMATION()
    if not _windows_kernel32().GetFileInformationByHandle(ctypes.c_void_p(handle), ctypes.byref(info)):
        raise UnsafeEntryError()
    return {
        "attributes": int(info.attributes),
        "size": (int(info.size_high) << 32) | int(info.size_low),
        "links": int(info.number_of_links),
        "identity": (int(info.volume_serial) << 64) | (int(info.file_index_high) << 32) | int(info.file_index_low),
        "write_time": (int(info.write_time.high) << 32) | int(info.write_time.low),
    }


def _windows_stable(before: dict[str, int], after: dict[str, int]) -> bool:
    return all(
        before[key] == after[key]
        for key in ("attributes", "identity", "links", "size", "write_time")
    )


def _open_windows_root(root: Path) -> dict[str, Any]:
    prepared = _prepare_root_path(root)
    anchor = prepared.anchor
    if not anchor or _windows_drive_type(anchor) == _DRIVE_REMOTE:
        raise UnsafeEntryError("unsafe_root")
    handles: list[int] = []
    current = Path(anchor)
    try:
        components = [current]
        for part in prepared.parts[1:]:
            current = current / part
            components.append(current)
        if len(components) > MAX_FILES:
            raise ResourceLimitError("resource_limit_files")
        for component in components:
            handle = _windows_open_handle(component)
            _register_open_resource(handles, handle, _windows_close_handle)
            info = _windows_info(handle)
            if info["attributes"] & _FILE_ATTRIBUTE_REPARSE_POINT:
                raise UnsafeEntryError("symlink")
            if not info["attributes"] & _FILE_ATTRIBUTE_DIRECTORY:
                raise UnsafeEntryError("invalid_root")
        return {
            "path": prepared,
            "handle": handles[-1],
            "ancestors": handles[:-1],
            "handle_count": len(handles),
        }
    except BaseException as error:
        for handle in reversed(handles):
            _windows_close_handle(handle)
        if isinstance(error, UnsafeEntryError) and error.code == "inspection_failed":
            raise UnsafeEntryError("invalid_root") from None
        raise


def _close_windows_root(root: dict[str, Any]) -> None:
    _windows_close_handle(root["handle"])
    for handle in reversed(root["ancestors"]):
        _windows_close_handle(handle)


def _windows_handle_to_fd(handle: int) -> int:
    import msvcrt

    return msvcrt.open_osfhandle(handle, os.O_RDONLY | getattr(os, "O_BINARY", 0))


def _walk_windows(
    directory: dict[str, Any], relative_directory: PurePosixPath, depth: int, state: dict[str, Any]
) -> None:
    if depth > MAX_DEPTH:
        raise ResourceLimitError("resource_limit_depth")
    initial_directory = _windows_info(directory["handle"])
    with os.scandir(directory["path"]) as iterator:
        names = _initial_names(iterator, state)
    state["windows_directories"].append(
        {
            "path": directory["path"],
            "handle": directory["handle"],
            "initial": initial_directory,
            "names": names,
        }
    )
    for name in names:
        _reserve_entry(state)
        relative = (relative_directory / name).as_posix()
        safe_path = _safe_entry_name(name) and _safe_relative_path(relative)
        location = relative if safe_path else _unsafe_location(state)
        if not safe_path:
            state["risks"].append({"code": "sensitive_path", "path": location})
            state["files"].append(_placeholder(location, "unknown"))
            continue
        _reserve_handle(state)
        try:
            handle = _windows_open_handle(directory["path"] / name)
        except BaseException:
            _release_handle(state)
            raise
        transferred = False
        retained = False
        try:
            info = _windows_info(handle)
            if info["attributes"] & _FILE_ATTRIBUTE_REPARSE_POINT:
                state["risks"].append({"code": "symlink", "path": relative})
                state["files"].append(_placeholder(relative, "link"))
                continue
            if info["attributes"] & _FILE_ATTRIBUTE_DEVICE:
                state["risks"].append({"code": "unsupported_entry", "path": relative})
                state["files"].append(_placeholder(relative, "unsupported"))
                continue
            if info["attributes"] & _FILE_ATTRIBUTE_DIRECTORY:
                child = {"path": directory["path"] / name, "handle": handle, "ancestors": []}
                _append_resource(state["windows_handles"], handle)
                retained = True
                _walk_windows(child, relative_directory / name, depth + 1, state)
                continue
            if info["links"] > 1:
                state["risks"].append({"code": "hardlink", "path": relative})
                state["files"].append(_placeholder(relative, "hardlink"))
                continue
            _reserve_bytes(state, info["size"])
            descriptor = _windows_handle_to_fd(handle)
            transferred = True
            _register_open_resource(state["windows_fds"], descriptor, os.close, state)
            record, payload, codes = _read_open_file(
                descriptor,
                info["size"],
                relative,
                0,
                lambda: _windows_stable(info, _windows_info(handle)),
            )
            state["windows_files"].append(
                {
                    "fd": descriptor,
                    "handle": handle,
                    "parent_handle": directory["handle"],
                    "name": name,
                    "initial": info,
                }
            )
            state["files"].append(record)
            if payload is not None:
                state["skill_payload"] = payload
            state["risks"].extend({"code": code, "path": relative} for code in codes)
        finally:
            if not transferred and not retained:
                _windows_close_handle(handle)
                _release_handle(state)


def _verify_windows_package(state: dict[str, Any]) -> None:
    try:
        for directory in state["windows_directories"]:
            current = _windows_info(directory["handle"])
            if not _windows_stable(directory["initial"], current):
                raise UnsafeEntryError("identity_changed")
            with os.scandir(directory["path"]) as iterator:
                names, overflow = _bounded_names(iterator, len(directory["names"]))
            if overflow or tuple(sorted(names)) != directory["names"]:
                raise UnsafeEntryError("identity_changed")
        for file_record in state["windows_files"]:
            current = _windows_info(file_record["handle"])
            if not _windows_stable(file_record["initial"], current):
                raise UnsafeEntryError("identity_changed")
    except UnsafeEntryError:
        raise
    except OSError:
        raise UnsafeEntryError("identity_changed") from None


def _close_windows_state(state: dict[str, Any]) -> None:
    for descriptor in reversed(state["windows_fds"]):
        try:
            os.close(descriptor)
        except OSError:
            pass
    for handle in reversed(state["windows_handles"]):
        _windows_close_handle(handle)


def _posix_device(metadata: Any) -> int:
    device = getattr(metadata, "st_dev", None)
    if not isinstance(device, int):
        raise UnsafeEntryError("unsupported_secure_traversal")
    return device


def _linux_openat2(directory_fd: int, name: str, flags: int) -> int:
    try:
        machine = os.uname().machine.lower()
    except (AttributeError, OSError):
        raise UnsafeEntryError("unsupported_secure_traversal") from None
    if machine not in _OPENAT2_MACHINES:
        raise UnsafeEntryError("unsupported_secure_traversal")
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        syscall = libc.syscall
    except (AttributeError, OSError):
        raise UnsafeEntryError("unsupported_secure_traversal") from None
    syscall.restype = ctypes.c_long
    how = _OPEN_HOW(flags=flags, mode=0, resolve=_OPENAT2_RESOLVE)
    result = syscall(
        ctypes.c_long(_SYS_OPENAT2),
        ctypes.c_int(directory_fd),
        ctypes.c_char_p(os.fsencode(name)),
        ctypes.byref(how),
        ctypes.c_size_t(ctypes.sizeof(how)),
    )
    if result < 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
    return int(result)


def _posix_open_child(name: str, flags: int, directory_fd: int) -> int:
    if sys.platform.startswith("linux"):
        return _linux_openat2(directory_fd, name, flags)
    raise UnsafeEntryError("unsupported_secure_traversal")


def _posix_binding_snapshot(metadata: Any) -> tuple[int, int, int | None, int | None]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        getattr(metadata, "st_mode", None),
        getattr(metadata, "st_nlink", None),
    )


def _close_posix_descriptors(descriptors: Any) -> None:
    closed: set[int] = set()
    for descriptor in descriptors:
        if descriptor in closed:
            continue
        closed.add(descriptor)
        try:
            os.close(descriptor)
        except OSError:
            pass


def _open_posix_root(root: Path) -> dict[str, Any]:
    if not sys.platform.startswith("linux"):
        raise UnsafeEntryError("unsupported_secure_traversal")
    if not all(
        hasattr(os, name) for name in ("O_DIRECTORY", "O_NOFOLLOW", "O_NONBLOCK")
    ):
        raise UnsafeEntryError("unsupported_secure_traversal")
    if os.open not in os.supports_dir_fd or os.stat not in os.supports_dir_fd or os.scandir not in os.supports_fd:
        raise UnsafeEntryError("unsupported_secure_traversal")
    prepared = _prepare_root_path(root)
    if len(prepared.parts) > MAX_FILES:
        raise ResourceLimitError("resource_limit_files")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    handles: list[int] = []
    root_chain: list[dict[str, Any]] = []
    try:
        descriptor = os.open("/", flags)
        _register_open_resource(handles, descriptor, os.close)
        metadata = os.fstat(descriptor)
        device = _posix_device(metadata)
        root_chain.append(
            {
                "fd": descriptor,
                "parent_fd": None,
                "name": None,
                "initial": _posix_binding_snapshot(metadata),
            }
        )
        for part in prepared.parts[1:]:
            try:
                child = _linux_openat2(descriptor, part, flags)
            except UnsafeEntryError:
                raise
            except OSError as error:
                code = (
                    "unsupported_secure_traversal"
                    if error.errno in {errno.E2BIG, errno.EINVAL, errno.ENOSYS, errno.EXDEV}
                    else "invalid_root"
                )
                raise UnsafeEntryError(code) from None
            _register_open_resource(handles, child, os.close)
            child_metadata = os.fstat(child)
            if _posix_device(child_metadata) != device:
                raise UnsafeEntryError("unsupported_secure_traversal")
            root_chain.append(
                {
                    "fd": child,
                    "parent_fd": descriptor,
                    "name": part,
                    "initial": _posix_binding_snapshot(child_metadata),
                }
            )
            descriptor = child
        if len(root_chain) == 1:
            if len(handles) >= MAX_FILES:
                raise ResourceLimitError("resource_limit_files")
            try:
                probe = _linux_openat2(descriptor, ".", flags)
            except UnsafeEntryError:
                raise
            except OSError as error:
                code = (
                    "unsupported_secure_traversal"
                    if error.errno in {errno.E2BIG, errno.EINVAL, errno.ENOSYS, errno.EXDEV}
                    else "invalid_root"
                )
                raise UnsafeEntryError(code) from None
            _register_open_resource(handles, probe, os.close)
            probe_metadata = os.fstat(probe)
            if _posix_device(probe_metadata) != device:
                raise UnsafeEntryError("unsupported_secure_traversal")
            descriptor = probe
            root_chain = [
                {
                    "fd": probe,
                    "parent_fd": None,
                    "name": None,
                    "initial": _posix_binding_snapshot(probe_metadata),
                }
            ]
        return {
            "path": prepared,
            "handle": descriptor,
            "ancestors": handles[:-1],
            "handle_count": len(handles),
            "device": device,
            "root_chain": root_chain,
        }
    except BaseException as error:
        _close_posix_descriptors(reversed(handles))
        if isinstance(error, UnsafeEntryError):
            raise
        if isinstance(error, OSError):
            raise UnsafeEntryError("invalid_root") from None
        raise


def _close_posix_root(root: dict[str, Any]) -> None:
    _close_posix_descriptors([root["handle"], *reversed(root["ancestors"])])


def _posix_snapshot(
    metadata: Any,
) -> tuple[int, int, int | None, int | None, int, int | None, int | None]:
    return (
        *_posix_binding_snapshot(metadata),
        metadata.st_size,
        getattr(metadata, "st_mtime_ns", None),
        getattr(metadata, "st_ctime_ns", None),
    )


def _block_unsupported_entry(relative: str, state: dict[str, Any]) -> None:
    state["risks"].append({"code": "unsupported_entry", "path": relative})
    state["files"].append(_placeholder(relative, "unsupported"))


def _close_new_posix_fd(descriptor: int, state: dict[str, Any]) -> None:
    try:
        os.close(descriptor)
    finally:
        _release_handle(state)


def _open_posix_entry(
    name: str, flags: int, parent_fd: int, state: dict[str, Any]
) -> int | None:
    _reserve_handle(state)
    try:
        return _posix_open_child(name, flags, parent_fd)
    except OSError as error:
        _release_handle(state)
        if error.errno == errno.EXDEV:
            return None
        raise
    except BaseException:
        _release_handle(state)
        raise


def _posix_entry_metadata(
    name: str, parent_fd: int, state: dict[str, Any]
) -> Any | None:
    if not sys.platform.startswith("linux"):
        return os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    path_flag = getattr(os, "O_PATH", None)
    if not isinstance(path_flag, int) or not path_flag:
        raise UnsafeEntryError("unsupported_secure_traversal")
    flags = path_flag | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    descriptor = _open_posix_entry(name, flags, parent_fd, state)
    if descriptor is None:
        return None
    try:
        return os.fstat(descriptor)
    finally:
        _close_new_posix_fd(descriptor, state)


def _walk_posix(
    descriptor: int,
    relative_directory: PurePosixPath,
    depth: int,
    state: dict[str, Any],
    parent_fd: int | None = None,
    name: str | None = None,
    is_root: bool = False,
) -> None:
    if depth > MAX_DEPTH:
        raise ResourceLimitError("resource_limit_depth")
    initial_directory = os.fstat(descriptor)
    initial_device = _posix_device(initial_directory)
    root_device = state.get("posix_root_dev")
    if root_device is None and depth == 0:
        state["posix_root_dev"] = initial_device
        root_device = initial_device
    if not isinstance(root_device, int):
        raise UnsafeEntryError("unsupported_secure_traversal")
    if initial_device != root_device:
        raise UnsafeEntryError("identity_changed")
    with os.scandir(descriptor) as iterator:
        names = _initial_names(iterator, state)
    state["posix_directories"].append(
        {
            "fd": descriptor,
            "parent_fd": parent_fd,
            "name": name,
            "is_root": is_root,
            "initial": _posix_snapshot(initial_directory),
            "names": names,
        }
    )
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    file_flags = (
        os.O_RDONLY
        | os.O_NOFOLLOW
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_NOCTTY", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    for name in names:
        _reserve_entry(state)
        relative = (relative_directory / name).as_posix()
        safe_path = _safe_entry_name(name) and _safe_relative_path(relative)
        location = relative if safe_path else _unsafe_location(state)
        if not safe_path:
            state["risks"].append({"code": "sensitive_path", "path": location})
            state["files"].append(_placeholder(location, "unknown"))
            continue
        before = _posix_entry_metadata(name, descriptor, state)
        if before is None:
            _block_unsupported_entry(relative, state)
            continue
        if stat.S_ISLNK(before.st_mode):
            state["risks"].append({"code": "symlink", "path": relative})
            state["files"].append(_placeholder(relative, "link"))
            continue
        if stat.S_ISDIR(before.st_mode):
            before_device = _posix_device(before)
            if before_device != root_device:
                _block_unsupported_entry(relative, state)
                continue
            child = _open_posix_entry(name, directory_flags, descriptor, state)
            if child is None:
                _block_unsupported_entry(relative, state)
                continue
            try:
                opened = os.fstat(child)
            except BaseException:
                _close_new_posix_fd(child, state)
                raise
            try:
                opened_device = _posix_device(opened)
                same_entry = stat.S_ISDIR(opened.st_mode) and (
                    _posix_binding_snapshot(before) == _posix_binding_snapshot(opened)
                )
            except BaseException:
                _close_new_posix_fd(child, state)
                raise
            if opened_device != root_device:
                _close_new_posix_fd(child, state)
                _block_unsupported_entry(relative, state)
                continue
            if not same_entry:
                _close_new_posix_fd(child, state)
                raise UnsafeEntryError("identity_changed")
            _register_open_resource(state["posix_fds"], child, os.close, state)
            _walk_posix(
                child,
                relative_directory / name,
                depth + 1,
                state,
                parent_fd=descriptor,
                name=name,
                is_root=False,
            )
            continue
        if not stat.S_ISREG(before.st_mode):
            _block_unsupported_entry(relative, state)
            continue
        before_device = _posix_device(before)
        if before_device != root_device:
            _block_unsupported_entry(relative, state)
            continue
        if before.st_nlink > 1:
            state["risks"].append({"code": "hardlink", "path": relative})
            state["files"].append(_placeholder(relative, "hardlink"))
            continue
        child = _open_posix_entry(name, file_flags, descriptor, state)
        if child is None:
            _block_unsupported_entry(relative, state)
            continue
        try:
            opened = os.fstat(child)
        except BaseException:
            _close_new_posix_fd(child, state)
            raise
        try:
            opened_device = _posix_device(opened)
            same_entry = (
                stat.S_ISREG(opened.st_mode)
                and opened.st_nlink == 1
                and _posix_binding_snapshot(before) == _posix_binding_snapshot(opened)
            )
        except BaseException:
            _close_new_posix_fd(child, state)
            raise
        if opened_device != root_device:
            _close_new_posix_fd(child, state)
            _block_unsupported_entry(relative, state)
            continue
        if not same_entry:
            _close_new_posix_fd(child, state)
            raise UnsafeEntryError("identity_changed")
        _register_open_resource(state["posix_fds"], child, os.close, state)
        _reserve_bytes(state, opened.st_size)
        initial = _posix_snapshot(opened)
        record, payload, codes = _read_open_file(
            child,
            opened.st_size,
            relative,
            stat.S_IMODE(opened.st_mode),
            lambda: initial == _posix_snapshot(os.fstat(child)),
        )
        state["posix_files"].append(
            {
                "fd": child,
                "parent_fd": descriptor,
                "name": name,
                "initial": initial,
            }
        )
        state["files"].append(record)
        if payload is not None:
            state["skill_payload"] = payload
        state["risks"].extend({"code": code, "path": relative} for code in codes)


def _verify_posix_package(state: dict[str, Any]) -> None:
    try:
        for file_record in state["posix_files"]:
            if file_record["initial"] != _posix_snapshot(os.fstat(file_record["fd"])):
                raise UnsafeEntryError("identity_changed")
            current = os.stat(
                file_record["name"],
                dir_fd=file_record["parent_fd"],
                follow_symlinks=False,
            )
            if file_record["initial"] != _posix_snapshot(current):
                raise UnsafeEntryError("identity_changed")
        directories = state["posix_directories"]
        children = [
            item
            for item in directories
            if not item.get("is_root", item.get("parent_fd") is None)
        ]
        roots = [
            item
            for item in directories
            if item.get("is_root", item.get("parent_fd") is None)
        ]
        for directory in [*reversed(children), *roots]:
            if directory["initial"] != _posix_snapshot(os.fstat(directory["fd"])):
                raise UnsafeEntryError("identity_changed")
            if directory.get("parent_fd") is not None:
                current = os.stat(
                    directory["name"],
                    dir_fd=directory["parent_fd"],
                    follow_symlinks=False,
                )
                if directory["initial"] != _posix_snapshot(current):
                    raise UnsafeEntryError("identity_changed")
            with os.scandir(directory["fd"]) as iterator:
                names, overflow = _bounded_names(iterator, len(directory["names"]))
            if overflow or tuple(sorted(names)) != directory["names"]:
                raise UnsafeEntryError("identity_changed")
    except UnsafeEntryError:
        raise
    except OSError:
        raise UnsafeEntryError("identity_changed") from None


def _verify_posix_root_chain(root: dict[str, Any]) -> None:
    try:
        for component in reversed(root["root_chain"][:-1]):
            if component["initial"] != _posix_binding_snapshot(
                os.fstat(component["fd"])
            ):
                raise UnsafeEntryError("identity_changed")
            if component["parent_fd"] is not None:
                current = os.stat(
                    component["name"],
                    dir_fd=component["parent_fd"],
                    follow_symlinks=False,
                )
                if component["initial"] != _posix_binding_snapshot(current):
                    raise UnsafeEntryError("identity_changed")
    except UnsafeEntryError:
        raise
    except OSError:
        raise UnsafeEntryError("identity_changed") from None


def _close_posix_state(state: dict[str, Any]) -> None:
    for descriptor in reversed(state["posix_fds"]):
        try:
            os.close(descriptor)
        except OSError:
            pass


def _collect_secure(root: os.PathLike[str] | str, state: dict[str, Any]) -> None:
    if os.name == "nt":
        opened = _open_windows_root(Path(root))
        try:
            state["open_count"] = opened["handle_count"]
            _walk_windows(opened, PurePosixPath(), 0, state)
            _verify_windows_package(state)
        finally:
            try:
                _close_windows_state(state)
            finally:
                try:
                    _close_windows_root(opened)
                finally:
                    state["open_count"] = 0
        return
    if os.name == "posix":
        opened = _open_posix_root(Path(root))
        try:
            state["open_count"] = opened["handle_count"]
            state["posix_root_dev"] = opened["device"]
            requested_root = opened["root_chain"][-1]
            _walk_posix(
                opened["handle"],
                PurePosixPath(),
                0,
                state,
                parent_fd=requested_root["parent_fd"],
                name=requested_root["name"],
                is_root=True,
            )
            _verify_posix_package(state)
            _verify_posix_root_chain(opened)
        finally:
            try:
                _close_posix_state(state)
            finally:
                try:
                    _close_posix_root(opened)
                finally:
                    state["open_count"] = 0
        return
    raise UnsafeEntryError("unsupported_secure_traversal")


def inspect_skill(
    root: Path,
    source: str | None,
    revision: str | None,
) -> dict[str, Any]:
    """Return a deterministic report for a local directory without running its files."""

    safe_source, safe_revision, initial_risks = _sanitize_metadata(source, revision)
    state = _new_state(initial_risks)
    collection_complete = False
    try:
        _collect_secure(root, state)
        collection_complete = True
    except ResourceLimitError as error:
        state["risks"].append({"code": error.code, "path": "."})
    except UnsafeEntryError as error:
        code = error.code if error.code in _BLOCKING_RISKS or error.code == "symlink" else "inspection_failed"
        state["risks"].append({"code": code, "path": "."})
    except OSError:
        state["risks"].append({"code": "inspection_failed", "path": "."})

    files = sorted(state["files"], key=lambda item: item["path"])
    frontmatter: dict[str, str] = {}
    frontmatter_verified = False
    payload = state["skill_payload"]
    if not collection_complete:
        pass
    elif payload is not None:
        try:
            frontmatter, frontmatter_verified = parse_simple_frontmatter(payload.decode("utf-8"))
        except UnicodeDecodeError:
            pass
        if not frontmatter_verified:
            state["risks"].append({"code": "frontmatter_unverified", "path": "SKILL.md"})
    elif any(item["path"] == "SKILL.md" for item in files):
        state["risks"].append({"code": "frontmatter_unverified", "path": "SKILL.md"})
    else:
        state["risks"].append({"code": "missing_skill_file", "path": "SKILL.md"})

    valid_frontmatter = bool(
        frontmatter_verified
        and _NAME_PATTERN.fullmatch(frontmatter.get("name", ""))
        and frontmatter.get("description", "").strip()
    )
    if frontmatter_verified and not valid_frontmatter:
        state["risks"].append({"code": "frontmatter_unverified", "path": "SKILL.md"})
    risks = _risk_records(state["risks"])
    blocking = any(item["code"] in _BLOCKING_RISKS for item in risks)
    return {
        "valid_skill": valid_frontmatter and not blocking,
        "frontmatter": frontmatter if frontmatter_verified else {},
        "files": files,
        "tree_hash": _tree_hash(files),
        "risks": risks,
        "source": safe_source,
        "revision": safe_revision,
    }


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        del message
        self.exit(2, json.dumps({"error": "usage_error"}) + "\n")


def _build_parser() -> argparse.ArgumentParser:
    parser = _SafeArgumentParser(description="Inspect one already-fetched local Agent Skill directory.")
    parser.add_argument("root", type=Path)
    parser.add_argument("--source")
    parser.add_argument("--revision")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _build_parser().parse_args(argv)
    try:
        report = inspect_skill(arguments.root, arguments.source, arguments.revision)
    except Exception:
        report = _empty_report(None, None, [{"code": "inspection_failed", "path": "."}])
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0 if report["valid_skill"] else 1


if __name__ == "__main__":
    sys.exit(main())
