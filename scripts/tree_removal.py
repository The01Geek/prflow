#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Recursive tree removal that survives Windows read-only entries and long paths.

`remove_tree(path, reasons=None)` deletes `path` and returns the paths it could not delete,
in their normal (unprefixed) form; an empty list means the tree is gone. An `OSError` from
its own filesystem calls or from a path-like's `__fspath__`, and a `RecursionError` from a
tree too deep for `shutil.rmtree`, are returned this way, never raised, and a `ValueError`
(a NUL byte, a bad path-like) is returned as `EINVAL`; one raised by the path-like's `__str__`
or by the `reasons` dict can propagate, and an argument that is not a path raises `TypeError`.
A `reasons` dict receives each returned path's first `OSError`; a path is returned once.
`describe(exc)` renders such an error's cause for a message.

* An empty path returns `[]`; a blank name, a bare root (`/`, a drive, a UNC share), a path
  that is `.` or a path with a `..` component (a UNC server or share and a drive-relative `C:..`
  included), or on Windows a component other than `.` made only of dots and spaces, is refused
  and returned, whether or not it exists.
* Otherwise a path `os.lstat` reports not found, or under a component that is not a folder,
  returns `[]`; one whose existence cannot be read is returned.
* A path that resolves to its own parent (a filesystem root), or that is the current folder
  itself, is refused and returned.
* A root that is a symlink or a junction (trailing separators and `.` ignored), cannot be inspected,
  or fails outside the per-entry handler is returned as given, minus any extended-length
  prefix; a refused link is neither deleted nor changed.
* On Windows a path found inside the tree is reported resolved through `os.path.realpath`.
* A delete that raises `PermissionError` on an entry that is neither a symlink nor a
  junction gets the owner-write bit added to its current permission bits and is retried once.
  When the link check, that `lstat` or that `chmod` fails, the entry is returned with the delete's
  error noted `retry not attempted: <cause>`; when the retry fails, with the retry's error after a
  best-effort restore of its saved bits, a failed restore noted on it. Any other failure is
  recorded without a `chmod`, and an entry that vanished mid-removal (its path no longer
  found, or under a component that is no longer a folder) counts as deleted.
* On Windows the removal runs through the extended-length (`\\\\?\\`) form, and a root is
  inspected through it when its plain form is not found or its name is too long, so a tree
  past 260 characters is deleted when Windows long paths are off.
"""

import errno
import inspect
import ntpath
import os
import posixpath
import shutil
import stat

# Reassignable so a test can force the Windows arm on a POSIX host.
HOST_OS_NAME = os.name


def _extended_path(text):
    r"""`text`, an absolute Windows path, in its extended-length form: `\\?\<drive path>`, or
    `\\?\UNC\<server\share...>` for a UNC path. An already-extended path is returned unchanged."""
    if text.startswith('\\\\?\\'):
        return text
    if text.startswith('\\\\'):
        return '\\\\?\\UNC\\' + text[2:]
    return '\\\\?\\' + text


def _strip_extended(text):
    """The inverse of `_extended_path`: `text` without a `\\\\?\\UNC\\` or `\\\\?\\` prefix."""
    if text.startswith('\\\\?\\UNC\\'):
        return '\\\\' + text[8:]
    if text.startswith('\\\\?\\'):
        return text[4:]
    return text


def _is_link_or_junction(path):
    """Raises OSError when `path` cannot be lstat'ed."""
    st = os.lstat(path)
    # The reparse-tag constant exists only on Windows builds of the stat module.
    junction_tag = getattr(stat, 'IO_REPARSE_TAG_MOUNT_POINT', None)
    return stat.S_ISLNK(st.st_mode) or (junction_tag is not None
                                        and getattr(st, 'st_reparse_tag', 0) == junction_tag)


def _record(path, exc, failures, reasons):
    # rmtree can report one path twice (a denied listing, then its rmdir): keep the first cause.
    shown = _strip_extended(path)
    if shown not in failures:
        failures.append(shown)
    if reasons is not None and isinstance(exc, OSError):
        reasons.setdefault(shown, exc)


def _vanished(exc, path):
    """Whether `exc` reports `path` missing and it is in fact gone, as rmtree counts a vanished entry."""
    if not isinstance(exc, (FileNotFoundError, NotADirectoryError)):
        return False
    try:
        return not _present(path)
    except OSError:
        return False


def _handle(func, path, exc, failures, reasons=None):
    """shutil.rmtree's error handler: fix a read-only entry and retry its delete once."""
    if _vanished(exc, path):
        return
    try:
        # Per call, not a module-level tuple: a patched os.unlink would stop matching and skip the retry.
        if (not isinstance(exc, PermissionError)
                or not any(func is delete for delete in (os.unlink, os.remove, os.rmdir))
                or _is_link_or_junction(path)):
            _record(path, exc, failures, reasons)
            return
        mode = stat.S_IMODE(os.lstat(path).st_mode)
        # Add the bit, never set the mode to it: S_IWRITE alone drops read and execute on POSIX.
        os.chmod(path, mode | stat.S_IWRITE)
    except OSError as fixup_exc:
        if _vanished(fixup_exc, path):
            return
        exc.add_note(f'retry not attempted: {describe(fixup_exc) or type(fixup_exc).__name__}')
        _record(path, exc, failures, reasons)
        return
    try:
        func(path)
    except OSError as retry_exc:
        if _vanished(retry_exc, path):
            return
        try:
            os.chmod(path, mode)
        except OSError as restore_exc:
            retry_exc.add_note(f'mode restore failed: {describe(restore_exc) or type(restore_exc).__name__}')
        _record(path, retry_exc, failures, reasons)


def _split_probe(path):
    """(drive, tail) of `path` minus trailing separators and `.` components, which make `lstat`
    follow a symlink root; an empty tail, `.` or a lone separator is a root or the current folder."""
    seps = '\\/' if HOST_OS_NAME == 'nt' else '/'
    drive, rest = (ntpath if HOST_OS_NAME == 'nt' else posixpath).splitdrive(path)
    trimmed = rest.rstrip(seps)
    while len(trimmed) > 1 and trimmed[-1] == '.' and trimmed[-2] in seps:
        trimmed = trimmed[:-1].rstrip(seps)
    return drive, trimmed or rest[:1]


def _present(path):
    """Whether `path` exists (a dangling link counts); raises OSError when that cannot be told.
    Not os.path.lexists: it reads a denied lstat as absent, so a root nobody inspected would read as gone."""
    try:
        os.lstat(path)
    except (FileNotFoundError, NotADirectoryError):
        return False
    return True


def _plain_missing(probe):
    """Whether the plain form of a Windows root reads as absent, so its extended form is tried;
    a name-too-long error counts as absent."""
    try:
        return not _present(probe)
    except OSError as exc:
        if exc.errno == errno.ENAMETOOLONG or getattr(exc, 'winerror', None) == 206:
            return True
        raise


def describe(exc: BaseException | None) -> str:
    """The cause of a returned path's `OSError` for a message: its strerror, or its lone message
    argument when it has none, then its notes; never its filename, which could carry the
    extended-length prefix."""
    if not isinstance(exc, OSError):
        return ''
    lone = exc.args[0] if len(exc.args) == 1 and isinstance(exc.args[0], str) else ''
    text = exc.strerror or lone
    return '; '.join(part for part in (text, *getattr(exc, '__notes__', ())) if part)


def _is_cwd(probe):
    """Whether `probe` is the current folder by identity (a case-insensitive or bind-mounted
    spelling included), or by resolved name on a volume reporting inode 0; a deleted current
    folder cannot be the target."""
    try:
        here = os.stat(os.curdir)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise OSError(exc.errno, f'cannot read the current folder to rule it out: {exc.strerror or exc}') from exc
    there = os.stat(probe)
    if not here.st_ino or not there.st_ino:
        # samestat would match every folder on the device.
        return (os.path.normcase(_strip_extended(os.path.realpath(probe)))
                == os.path.normcase(_strip_extended(os.path.realpath(os.curdir))))
    return os.path.samestat(there, here)


def remove_tree(path, reasons: dict[str, OSError] | None = None) -> list[str]:
    """Delete the tree at `path`; return the paths that could not be deleted (see module doc)."""
    failures = []
    try:
        path = os.fsdecode(os.fspath(path))
        if not path:
            return []
        drive, tail = _split_probe(path)
        seps = '\\/' if HOST_OS_NAME == 'nt' else '/'
        # The drive too, split apart from the tail: splitdrive files a UNC server and share there,
        # and a drive-relative 'C:..' puts its '..' at the start of the tail.
        parts = [p for s in (drive, tail) for p in ''.join('/' if c in seps else c for c in s).split('/')]
        # Win32 trims a name's trailing spaces and dots; refusing such a name anywhere is the safe side.
        climbs = any(p == '..' or (HOST_OS_NAME == 'nt' and p not in ('', '.') and not p.rstrip(' .'))
                     for p in parts)
        if not tail.strip() or tail in ('.', '/', '\\') or climbs:
            # Windows resolves a blank name to the current folder; a .. can climb out through a link.
            _record(path, OSError(errno.EINVAL, 'a blank name, a .. component, the current folder or a root'
                                  ' is refused'), failures, reasons)
            return failures
        probe = drive + tail
        if HOST_OS_NAME == 'nt' and _plain_missing(probe):
            # A root past 260 characters is visible only in its extended-length form.
            probe = _extended_path(os.path.abspath(probe))
        if not _present(probe):
            return []
        if _is_link_or_junction(probe):
            _record(path, OSError(errno.ELOOP, 'a symlink or junction root is refused'), failures, reasons)
            return failures
        # Decide on where the path resolves, as rmtree will: Windows strips trailing spaces and dots.
        resolved = _strip_extended(os.path.realpath(probe))
        if os.path.dirname(resolved) == resolved:
            _record(path, OSError(errno.EINVAL, 'resolves to a filesystem root'), failures, reasons)
            return failures
        if _is_cwd(probe):
            _record(path, OSError(errno.EINVAL, 'is the current folder'), failures, reasons)
            return failures
        target = _extended_path(os.path.realpath(probe)) if HOST_OS_NAME == 'nt' else probe
    except ValueError as exc:
        _record(path if isinstance(path, str) else str(path), OSError(errno.EINVAL, str(exc)), failures, reasons)
        return failures
    except OSError as exc:
        _record(path if isinstance(path, str) else str(path), exc, failures, reasons)
        return failures

    def onexc(func, failed, exc):
        _handle(func, failed, exc, failures, reasons)

    def onerror(func, failed, exc_info):
        _handle(func, failed, exc_info[1], failures, reasons)

    # onexc exists from Python 3.12, where onerror is deprecated; the floor is 3.11.
    handler = ({'onexc': onexc} if 'onexc' in inspect.signature(shutil.rmtree).parameters
               else {'onerror': onerror})
    try:
        shutil.rmtree(target, **handler)
    except OSError as exc:
        _record(path, exc, failures, reasons)
    except RecursionError as exc:
        # Not dead code: a recursive rmtree (the 3.11 floor's) can exhaust the limit on a deep tree.
        _record(path, OSError(f'recursion limit reached while removing the tree: {exc}'), failures, reasons)
    return failures
