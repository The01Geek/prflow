#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Deterministic review-engine setup and return-file assembly.

Reached through `review-dirty-tree.sh engine-setup|engine-return`, the granted head, so
one invocation replaces the run of one-value git turns Phase 0.2/0.3/0.5 cost and the
hand-typed mechanical half of the engine return file.

Subcommands (the wrapper drives the first two as a pair):
    setup-prepare  produce the local-diff cache fail-closed, derive the changed-file
                   table, counts and mechanical flags, write the root-identity manifest,
                   mint Phase 1's work directory (`phase1_work_dir`) and, on more than
                   BATCH_SIZE changed files, write each batch's slice of the published
                   diff (`batches`: `k`, `first`/`last` into `files`, `slice` path; a
                   slice that cannot be written or re-counts wrong is `unavailable`
                   with a warning, never a stop), and persist `engine-setup.json` in
                   the run directory. Prints `record:<path>` on success; on `empty` or
                   a stop, the result JSON.
    setup-emit     print the persisted record as one compact JSON line, adding the
                   dirty-tree snapshot object ID — stdout only, never written to
                   agent-writable scratch.
    return         splice the mechanical fields (`dispatch_mode`, `diff_produced_at_head`,
                   and `checklist` joined by id with its verification rows) into the
                   model-authored part, validate the whole return, write it atomically.
    view-materialize  materialize a commit-bound source view (issue #851): a run-scoped
                   directory of blobs from `git ls-tree`/`git cat-file` plus an
                   `inventory.json` manifest, so checklist generation and verification read
                   repository evidence from the reviewed commit instead of the checkout.
                   Harness-instruction files (CLAUDE.md/AGENTS.md at any depth, any path
                   under a `.claude/` dir) are stored under a `.src` suffix; symlink,
                   submodule and Git LFS pointer entries are recorded, never followed. Fails
                   closed (an unavailable commit, failed read, partial write or unsafe path)
                   and never executes, imports or sources the materialized bytes, or touches
                   the checkout/index.

Every result is one JSON object whose `status` is `ok`, `empty` (setup only: the diff has
no rows) or `error`, and an error's `step` is one of STOP_STEPS. Exit codes: 0 ok/empty,
1 error (a setup error raised after the run directory resolved has already removed
`diff.raw-candidate` and `diff.patch`), 2 usage.
"""

import argparse
import errno
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

CONFIG_ONLY_EXTS = {'.yml', '.yaml', '.json', '.md', '.toml', '.ini', '.lock', '.txt'}
# Phase 1.1's batching rule: at most this many changed files per checklist-generator batch.
BATCH_SIZE = 10
NEW_TYPE_RE = re.compile(
    rb'^\+\s*(?:(?:final|abstract|readonly|export(?:\s+default)?|public|pub)\s+)*'
    rb'(class|interface|type|enum|struct|trait)\s+\w+')
LOGS_HEADER_RE = re.compile(rb' [ab]/\.prflow/logs/')
ENUMERATE_RE = re.compile(
    r'(?i)(git ls-files|glob|os\.walk|listdir|rglob|find |grep -[a-z]*[rl]|for .+ in |'
    r'(^|[^a-z_])(every|each|all)([^a-z_]|$))')
ASSERT_RE = re.compile(
    r'(?i)(assert|superset|subset|exhaustive|coverage|wc -l|len\(|count|-eq |==|'
    r'(^|[^a-z_])(missing|none|no other|remaining)([^a-z_]|$))')
SAFE_COMPONENT_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*$')
HEX40_RE = re.compile(r'^[0-9a-f]{40}([0-9a-f]{24})?$')
HINT_CAP = 24
HINT_WIDTH = 160
RETURN_REQUIRED = (
    'root_completeness', 'phase3_findings', 'phase3_dispatched', 'expected_reviewers',
    'plan_eligible', 'plan_exclusions', 'phase3_failed_agents', 'diff_profile',
    'cap_drops', 'acceptance_criteria', 'verdict', 'report')
RETURN_LISTS = ('phase3_findings', 'phase3_dispatched', 'expected_reviewers',
                'plan_eligible', 'plan_exclusions', 'phase3_failed_agents')
# The verdict fields spliced into the engine-return checklist by cmd_return's join by id. A
# field missing here is silently dropped: view_revision is the collector's provenance input
# (issue #851), and a dropped severity fails closed to critical downstream (issue #1220).
VERDICT_KEYS = ('verdict', 'raw_verdict', 'normalized', 'evidence', 'file_checked',
                'normalization_ineligible', 'view_revision', 'demoted', 'severity')
RETURN_SPLICED = ('dispatch_mode', 'diff_produced_at_head', 'checklist')

# Harness-instruction files (issue #851 AC8): the harness loads a nested CLAUDE.md/AGENTS.md
# as instructions when any file in its subtree is read, and every path under a .claude/
# directory is a harness-owned instruction surface. Materializing PR-authored copies verbatim
# would instruct every agent that reads the view, so they are stored under a `.src` suffix and
# mapped in the inventory: the harness loads none of them, and a claim about them still reads
# their bytes.
HARNESS_INSTRUCTION_BASENAMES = frozenset(('CLAUDE.md', 'AGENTS.md'))
SRC_SUFFIX = '.src'
# git ls-tree/cat-file mode octets for the entry kinds the view records-but-never-materializes.
GIT_MODE_SYMLINK = '120000'
GIT_MODE_SUBMODULE = '160000'
# A Git LFS pointer blob opens with this spec line; it is recorded as a pointer, its small
# pointer bytes stored, never resolved to the large object it names.
LFS_POINTER_PREFIX = b'version https://git-lfs.github.com/spec/'


STOP_STEPS = frozenset((
    'arguments', 'repo-root', 'slug', 'base-resolution', 'pin-base', 'head', 'producer',
    'raw-candidate', 'filter', 'published-count', 'numstat', 'file-table', 'root-identity',
    'filesystem', 'setup-record', 'authored-part', 'checklist',
    # issue #851 source-view producer stops
    'view-arguments', 'view-commit', 'view-lstree', 'view-catfile', 'view-path', 'view-write'))


class Stop(Exception):
    """A fail-closed stop: `step` names where, `reason` quotes the evidence."""

    def __init__(self, step, reason):
        if step not in STOP_STEPS:
            raise ValueError(f'unregistered stop step {step!r}')
        super().__init__(reason)
        self.step = step
        self.reason = reason


def _git(args, cwd, stdout=subprocess.PIPE):
    # Neutralize the two consumer settings that drop the a/ b/ boundary the logs filter
    # anchors on; without this the filter is silently inert under either.
    # GIT_TERMINAL_PROMPT=0: a fetch that wants credentials fails instead of waiting on a prompt.
    return subprocess.run(
        ['git', '-c', 'diff.noprefix=false', '-c', 'diff.mnemonicPrefix=false', *args],
        cwd=cwd, stdout=stdout, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, check=False,
        env={**os.environ, 'GIT_TERMINAL_PROMPT': '0'})


def _err(proc):
    text = proc.stderr.decode('utf-8', 'replace').strip()
    return text.splitlines()[-1] if text else f'exit {proc.returncode}, no stderr'


def _emit(obj):
    sys.stdout.write(json.dumps(obj, separators=(',', ':'), ensure_ascii=False) + '\n')


def _repo_root():
    proc = _git(['rev-parse', '--show-toplevel'], None)
    if proc.returncode != 0 or not proc.stdout.strip():
        raise Stop('repo-root', _err(proc))
    return Path(proc.stdout.decode('utf-8', 'replace').strip())


def _component(value, name):
    if not isinstance(value, str) or not SAFE_COMPONENT_RE.match(value) or '..' in value:
        raise Stop('arguments', f'{name} {value!r} is not a safe path component')
    return value


def _slug(args, root):
    if args.slug:
        return _component(args.slug, 'slug')
    if args.pr:
        if not args.pr.isdigit():
            raise Stop('arguments', f'--pr {args.pr!r} is not numeric')
        return f'pr-{args.pr}'
    proc = _git(['branch', '--show-current'], root)
    branch = proc.stdout.decode('utf-8', 'replace').strip() if proc.returncode == 0 else ''
    slug = re.sub(r'[^a-z0-9._-]', '', branch.replace('/', '-').lower())
    if not slug:
        raise Stop('slug', 'no PR number and no current branch name; pass --slug')
    return _component(slug, 'slug')


def _reachable(base, root):
    return _git(['merge-base', base, 'HEAD'], root).returncode == 0


def _resolve_base(args, root, warnings):
    branch = args.base_branch
    if args.mode == 'current-branch':
        return f'origin/{branch}'
    refspec = f'+refs/heads/{branch}:refs/remotes/origin/{branch}'
    if _git(['fetch', 'origin', refspec], root).returncode == 0:
        base = f'origin/{branch}'
        if not _reachable(base, root):
            if _git(['fetch', '--unshallow', 'origin', refspec], root).returncode != 0:
                warnings.append('base unshallow fetch failed; probed merge-base once more')
            if not _reachable(base, root):
                raise Stop('base-resolution', 'base remains unreachable after unshallow retry')
    else:
        probe = _git(['ls-remote', '--heads', 'origin', f'refs/heads/{branch}'], root)
        if probe.returncode != 0:
            raise Stop('base-resolution',
                       f"could not confirm whether PR base ref '{branch}' was deleted: {_err(probe)}")
        if probe.stdout.strip():
            raise Stop('base-resolution',
                       f"PR base ref '{branch}' exists but its explicit-refspec fetch failed")
        if not args.base_sha:
            raise Stop('base-resolution', f"PR base ref '{branch}' is absent and no --base-sha was retained")
        base = args.base_sha
        warnings.append(f"PR base ref '{branch}' is absent on origin; using retained base SHA {base}")
        if not _reachable(base, root):
            raise Stop('base-resolution', 'retained base SHA is unreachable')
    if args.configured_base and args.configured_base != branch:
        warnings.append(f"PR base '{branch}' differs from configured checkpoint base "
                        f"'{args.configured_base}'; merged checkpoint content can re-enter the review diff")
    return base


def _name_status(pinned, root):
    proc = _git(['diff', '--name-status', '-z', f'{pinned}...HEAD'], root)
    if proc.returncode != 0:
        raise Stop('producer', _err(proc))
    fields = proc.stdout.split(b'\0')
    rows, i = [], 0
    while i < len(fields) and fields[i]:
        status = fields[i].decode('ascii', 'replace')
        take = 2 if status[:1] in ('R', 'C') else 1
        paths = [f.decode('utf-8', 'replace') for f in fields[i + 1:i + 1 + take]]
        if len(paths) != take:
            raise Stop('producer', 'name-status output ended inside a record')
        rows.append((status, paths))
        i += 1 + take
    return rows


def _numstat(pinned, root):
    proc = _git(['diff', '--numstat', '-z', f'{pinned}...HEAD'], root)
    if proc.returncode != 0:
        raise Stop('numstat', _err(proc))
    fields = proc.stdout.split(b'\0')
    stats, i = {}, 0
    while i < len(fields) and fields[i]:
        parts = fields[i].split(b'\t', 2)
        if len(parts) != 3:
            raise Stop('numstat', 'unparseable numstat record')
        if parts[2]:
            path, i = parts[2], i + 1
        else:
            if i + 2 >= len(fields):
                raise Stop('numstat', 'numstat output ended inside a rename record')
            path, i = fields[i + 2], i + 3
        counts = [int(p) if p.isdigit() else None for p in parts[:2]]
        stats[path.decode('utf-8', 'replace')] = counts
    return stats


def _count_sections(path):
    total = logs = 0
    with open(path, 'rb') as handle:
        for line in handle:
            if line.startswith(b'diff --git'):
                total += 1
                if LOGS_HEADER_RE.search(line):
                    logs += 1
    return total, logs


def _filter_logs(raw, published):
    # Header-anchored exactly like the fallback `awk` filter, so a rename out of .prflow/logs/
    # is dropped by both; change the two together or the helper and the fallback review different diffs.
    kept, in_logs = 0, False
    with open(raw, 'rb') as src, open(published, 'wb') as dst:
        for line in src:
            if line.startswith(b'diff --git'):
                in_logs = bool(LOGS_HEADER_RE.search(line))
                if not in_logs:
                    kept += 1
            if not in_logs:
                dst.write(line)
    return kept


def _is_config(path):
    return os.path.splitext(path)[1].lower() in CONFIG_ONLY_EXTS


def _scan_added(published):
    """One pass over the published diff: new-type and added-code flags, audit hints."""
    has_new_types = added_code = False
    per_file, current, new_line = {}, None, 0
    with open(published, 'rb') as handle:
        for line in handle:
            if line.startswith(b'diff --git'):
                current = None
            elif line.startswith(b'+++ '):
                name = line[4:].rstrip(b'\r\n')
                current = (name[2:].decode('utf-8', 'replace')
                           if name.startswith(b'b/') else None)
            elif line.startswith(b'@@'):
                match = re.match(rb'@@ -\d+(?:,\d+)? \+(\d+)', line)
                new_line = int(match.group(1)) if match else 0
            elif current is not None and line.startswith(b'+'):
                text = line[1:].decode('utf-8', 'replace').rstrip('\r\n')
                if not _is_config(current):
                    added_code = True
                    if NEW_TYPE_RE.match(line):
                        has_new_types = True
                entry = per_file.setdefault(current, {'enum': [], 'assert': []})
                if ENUMERATE_RE.search(text):
                    entry['enum'].append((new_line, text))
                if ASSERT_RE.search(text):
                    entry['assert'].append((new_line, text))
                new_line += 1
            elif current is not None and line.startswith(b' '):
                new_line += 1
    hints, truncated = [], False
    for path, entry in per_file.items():
        if not (entry['enum'] and entry['assert']):
            continue
        for number, text in sorted(set(entry['enum'][:3] + entry['assert'][:3])):
            if len(hints) >= HINT_CAP:
                truncated = True
                break
            hints.append({'file': path, 'line': number, 'text': text.strip()[:HINT_WIDTH]})
    return has_new_types, added_code, hints, truncated


def _root_identity(args, run_dir, root):
    """Write the bundle manifest; any shortfall is `underived` and authors nothing."""
    if not args.engine_dir:
        return 'skipped'
    engine = Path(args.engine_dir)
    phases = sorted(p.name for p in (engine / 'phases').glob('*.md')) if (engine / 'phases').is_dir() else []
    paths = [engine / 'SKILL.md'] + [engine / 'phases' / name for name in phases]
    if not phases or not all(p.is_file() for p in paths):
        return 'underived'
    proc = _git(['hash-object', '--', *[str(p) for p in paths]], root)
    hashes = proc.stdout.decode('ascii', 'replace').split()
    if proc.returncode != 0 or len(hashes) != len(paths) or not all(HEX40_RE.match(h) for h in hashes):
        return 'underived'
    if args.identity_hashes:
        held = sorted(h for h in re.split(r'[,\s]+', ' '.join(args.identity_hashes)) if h)
        if held != sorted(hashes):
            return 'mismatch'
    manifest = {'root': str(engine / 'SKILL.md'), 'root_hash': hashes[0],
                'references': {f'phases/{name}': digest for name, digest in zip(phases, hashes[1:])}}
    _write_atomic(run_dir / 'root-identity.json', json.dumps(manifest, indent=2) + '\n')
    return 'written'


def _write_atomic(path, text):
    tmp = path.with_name(path.name + '.tmp')
    try:
        tmp.write_text(text, encoding='utf-8')
        os.replace(tmp, path)
    except OSError as exc:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise Stop('filesystem', f'could not write {path}: {exc}') from exc


def _sections_of(row):
    # A typechange row emits two `diff --git` sections; every other status one — the same
    # rule the file-table equation in _prepare applies.
    return 2 if row['s'].startswith('T') else 1


def _slice_batches(published, run_dir, rel, files, warnings):
    """Phase 1.1's batches over the published diff, each slice written once.

    Batch k (1-based) owns rows `first`..`last` of the file table, at most BATCH_SIZE, and
    its slice holds exactly those rows' `diff --git` sections in document order. The mapping
    is positional: the table and the patch come from the same diff queue in the same order,
    and _prepare has already stopped unless the table's section total equals the published
    count. Each slice is written to a `.tmp` sibling, re-counted, then moved into place; a
    slice that cannot be written or re-counts wrong is reported `unavailable` with a warning
    (the prose keeps its own fence for that batch), and the published diff is never touched.
    """
    if len(files) <= BATCH_SIZE:
        return [{'k': 1, 'first': 1, 'last': len(files), 'slice': f'{rel}/diff.patch'}]
    batches, bounds, section = [], [], 0
    for k, start in enumerate(range(0, len(files), BATCH_SIZE), start=1):
        rows = files[start:start + BATCH_SIZE]
        count = sum(_sections_of(row) for row in rows)
        bounds.append((section + count - 1, count))  # last section index owned, expected count
        section += count
        batches.append({'k': k, 'first': start + 1, 'last': start + len(rows),
                        'slice': f'{rel}/batch-{k}.patch'})
    failed, handle, index, n = {}, None, -1, -1

    def fail(k, reason):
        failed[k] = reason
        warnings.append(f'batch {k} slice unavailable: {reason}')

    with open(published, 'rb') as src:
        for line in src:
            if line.startswith(b'diff --git'):
                n += 1
                while index < len(bounds) and (index < 0 or n > bounds[index][0]):
                    # Entering the next batch: close the previous slice, open this one.
                    if handle is not None:
                        handle.close()
                        handle = None
                    index += 1
                    if index < len(bounds) and index + 1 not in failed:
                        try:
                            handle = open(run_dir / f'batch-{index + 1}.patch.tmp', 'wb')
                        except OSError as exc:
                            fail(index + 1, f'open: {exc}')
            if handle is None:
                continue
            try:
                handle.write(line)
            except OSError as exc:
                fail(index + 1, f'write: {exc}')
                handle.close()
                handle = None
    if handle is not None:
        handle.close()
    for batch, (_, count) in zip(batches, bounds):
        k = batch['k']
        tmp, final = run_dir / f'batch-{k}.patch.tmp', run_dir / f'batch-{k}.patch'
        if k not in failed:
            try:
                got, _ = _count_sections(tmp)
                if got != count:
                    fail(k, f'slice holds {got} sections, batch expects {count}')
                else:
                    os.replace(tmp, final)
            except OSError as exc:
                fail(k, f'verify: {exc}')
        if k in failed:
            batch['slice'] = 'unavailable'
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
    return batches


def _prepare(args):
    root = _repo_root()
    run_id = _component(args.run_id, 'run-id')
    slug = _slug(args, root)
    run_dir = root / '.prflow' / 'tmp' / 'review' / slug / run_id
    raw, published = run_dir / 'diff.raw-candidate', run_dir / 'diff.patch'
    warnings = []
    try:
        run_dir.mkdir(parents=True, exist_ok=True)
        for stale in (raw, published, run_dir / 'engine-setup.json'):
            stale.unlink(missing_ok=True)
        base = _resolve_base(args, root, warnings)
        pin = _git(['rev-parse', '--verify', f'{base}^{{commit}}'], root)
        pinned = pin.stdout.decode('ascii', 'replace').strip()
        if pin.returncode != 0 or not HEX40_RE.match(pinned):
            raise Stop('pin-base', _err(pin))
        head = _git(['rev-parse', '--verify', 'HEAD^{commit}'], root)
        head_sha = head.stdout.decode('ascii', 'replace').strip()
        if head.returncode != 0 or not HEX40_RE.match(head_sha):
            raise Stop('head', _err(head))
        rows = _name_status(pinned, root)
        if not rows:
            return {'status': 'empty', 'slug': slug, 'run_id': run_id, 'base': base,
                    'base_sha': pinned, 'head_sha': head_sha, 'warnings': warnings}
        typechange = sum(1 for status, _ in rows if status.startswith('T'))
        with open(raw, 'wb') as handle:
            produced = _git(['diff', f'{pinned}...HEAD'], root, stdout=handle)
        if produced.returncode != 0:
            raise Stop('raw-candidate', _err(produced))
        raw_sections, logs_sections = _count_sections(raw)
        if raw_sections != len(rows) + typechange:
            raise Stop('raw-candidate', f'raw sections {raw_sections} != rows {len(rows)} + typechange {typechange}')
        kept = _filter_logs(raw, published)
        if kept != raw_sections - logs_sections:
            raise Stop('filter', f'published stream {kept} != raw {raw_sections} - logs {logs_sections}')
        on_disk, _ = _count_sections(published)
        if on_disk != kept:
            raise Stop('published-count', f'published file {on_disk} != published stream {kept}')
        raw.unlink(missing_ok=True)

        stats = _numstat(pinned, root)
        files, expected = [], 0
        for status, paths in rows:
            if any(p.startswith('.prflow/logs/') for p in paths):
                continue
            expected += 2 if status.startswith('T') else 1
            added, deleted = stats.get(paths[-1], [None, None])
            entry = {'s': status, 'p': paths[-1], 'a': added, 'd': deleted}
            if len(paths) == 2:
                entry['from'] = paths[0]
            files.append(entry)
        if expected != kept:
            # A table that disagrees with the cache would leave a file out of every batch slice.
            raise Stop('file-table', f'changed-file table expects {expected} sections but diff.patch holds {kept}')
        changed_lines = sum((f['a'] or 0) + (f['d'] or 0) for f in files)
        has_new_types, added_code, hints, truncated = _scan_added(published)
        test_path = any(re.search(r'(?i)test|spec', f['p']) for f in files)
        identity = _root_identity(args, run_dir, root)
        if identity in ('underived', 'mismatch'):
            raise Stop('root-identity', f'identity: {identity}')
        rel = run_dir.relative_to(root).as_posix()
        # Phase 1's work directory: a fresh unpredictable token per entry keeps a re-entrant
        # entry (same run-id, same iteration) from reading this entry's intermediates; the
        # checklist helper refuses a token shorter than its floor, so mint well above it.
        work_dir = run_dir / f'phase1-{secrets.token_hex(8)}'
        try:
            work_dir.mkdir()
        except OSError as exc:
            # A token collision or an unwritable run directory is a fail-closed stop, never
            # a traceback: the enclosing handler removes both caches on a Stop.
            raise Stop('filesystem', f'could not create {work_dir}: {exc}') from exc
        batches = _slice_batches(published, run_dir, rel, files, warnings)
        result = {
            'status': 'ok', 'slug': slug, 'run_id': run_id, 'run_dir': rel,
            'diff_path': f'{rel}/diff.patch', 'mode': args.mode, 'base': base,
            'base_sha': pinned, 'head_sha': head_sha,
            'sections': {'rows': len(rows), 'typechange': typechange, 'raw': raw_sections,
                         'logs': logs_sections, 'published': kept},
            'files': files, 'file_count': len(files), 'changed_lines': changed_lines,
            'phase1_work_dir': f'{rel}/{work_dir.name}', 'batches': batches,
            'flags': {'small_diff': changed_lines < 100 and len(files) <= 3,
                      'config_only': all(_is_config(f['p']) for f in files),
                      'has_new_types': has_new_types,
                      'test_relevant': test_path or added_code},
            'audit_hints': hints, 'audit_hints_truncated': truncated,
            'root_identity': identity, 'warnings': warnings}
        # Inside the fail-closed block: a record that cannot be written removes the caches too.
        _write_atomic(run_dir / 'engine-setup.json', json.dumps(result) + '\n')
        result['record'] = str(run_dir / 'engine-setup.json')
        return result
    except (Stop, OSError) as exc:
        for stale in (raw, published):
            try:
                stale.unlink(missing_ok=True)
            except OSError:
                pass
        if isinstance(exc, Stop):
            raise
        raise Stop('filesystem', str(exc)) from exc


def cmd_setup_prepare(args):
    result = _prepare(args)
    if result['status'] == 'empty':
        _emit(result)
        return 0
    sys.stdout.write(f"record:{result['record']}\n")
    return 0


def cmd_setup_emit(args):
    record = _load_object(Path(args.record), 'setup-record')
    oid = args.snapshot_oid.strip()
    record['snapshot_oid'] = oid if HEX40_RE.match(oid) else 'unavailable'
    _emit(record)
    return 0


def _load_object(path, what):
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise Stop(what, f'{path}: {exc}') from exc
    if not isinstance(value, dict):
        raise Stop(what, f'{path}: expected a JSON object, found {type(value).__name__}')
    return value


def _verification_rows(path):
    """(rows by id, state). Best-effort: any shape but rows-by-id merges nothing and says why."""
    if not path.exists():
        return {}, 'absent'
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}, 'unreadable'
    if isinstance(value, dict):
        value = next((value[k] for k in ('items', 'results', 'verification')
                      if isinstance(value.get(k), list)), None)
    if not isinstance(value, list):
        return {}, 'wrong-type'
    rows = {row['id']: row for row in value
            if isinstance(row, dict) and isinstance(row.get('id'), (str, int))
            and not isinstance(row.get('id'), bool)}
    return rows, ('joined' if rows else 'no-rows')


def cmd_return(args):
    run_dir = Path(args.run_dir)
    if args.entry not in ('step1', 'shadow') or not args.iteration.isdigit():
        raise Stop('arguments', '--entry is step1|shadow and --iteration is a number')
    authored = _load_object(Path(args.authored), 'authored-part')
    clash = [key for key in RETURN_SPLICED if key in authored]
    if clash:
        raise Stop('authored-part', f'carries helper-owned field(s): {", ".join(clash)}')
    missing = [key for key in RETURN_REQUIRED if key not in authored]
    if missing:
        raise Stop('authored-part', f'missing field(s): {", ".join(missing)}')
    wrong = [key for key in RETURN_LISTS if not isinstance(authored[key], list)]
    if wrong:
        raise Stop('authored-part', f'not an array: {", ".join(wrong)}')
    for key in ('verdict', 'report'):
        if not isinstance(authored[key], str) or not authored[key].strip():
            raise Stop('authored-part', f'{key} must be a nonempty string')
    # The fixer's criterion-conflict guard reads this; only "" means none resolved.
    if not isinstance(authored['acceptance_criteria'], str):
        raise Stop('authored-part', 'acceptance_criteria must be a string ("" when none resolved), '
                   f'found {type(authored["acceptance_criteria"]).__name__}')
    head = args.head.strip()
    if not HEX40_RE.match(head):
        raise Stop('arguments', '--head is the commit Phase 0.2 produced diff.patch at, as full hex')
    result = {'dispatch_mode': 'fanned-out', **authored, 'diff_produced_at_head': head}
    checklist_items, merged, verification = 'skipped', 0, 'skipped'
    if not args.no_checklist:
        path = run_dir / f'checklist-iter-{args.iteration}.json'
        try:
            checklist = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            raise Stop('checklist', f'{path}: {exc}') from exc
        if isinstance(checklist, dict) and isinstance(checklist.get('checklist'), list):
            checklist = checklist['checklist']
        if not isinstance(checklist, list) or not all(isinstance(item, dict) for item in checklist):
            raise Stop('checklist', f'{path}: expected an array of item objects')
        verdicts, verification = _verification_rows(run_dir / f'verification-iter-{args.iteration}.json')
        merged = 0
        for item in checklist:
            row = verdicts.get(item.get('id'))
            if row:
                merged += 1
                for key in VERDICT_KEYS:
                    if key in ('verdict', 'severity') and key in row:
                        item[key] = row[key]  # the stored (gated, fail-closed) value beats a preset one
                    elif key in row:
                        item.setdefault(key, row[key])
        result['checklist'] = checklist
        checklist_items = len(checklist)
    out = run_dir / f'engine-return-{args.entry}-iter-{args.iteration}.json'
    text = json.dumps(result, indent=1, ensure_ascii=False) + '\n'
    _write_atomic(out, text)
    _emit({'status': 'ok', 'path': out.as_posix(), 'bytes': len(text.encode('utf-8')),
           'checklist_items': checklist_items, 'verification': verification,
           'verdicts_merged': merged,
           'dispatch_mode': 'fanned-out'})
    return 0


def _is_harness_instruction(path):
    """True for a harness-instruction file (issue #851 AC8): a CLAUDE.md / AGENTS.md at any
    depth, or any path under a `.claude/` directory at any depth."""
    parts = path.split('/')
    if parts[-1] in HARNESS_INSTRUCTION_BASENAMES:
        return True
    return '.claude' in parts[:-1]


def _safe_view_path(path, view_dir):
    """Resolve a repo-relative entry path under `view_dir`, rejecting any escape (an
    absolute component, a `..` hop, or a join that resolves outside the view). The
    harness-instruction `.src` rename is applied to the stored name, never to the
    inventory's original `path`. Returns (stored_relpath, target_Path, renamed_bool)."""
    if not path or path.startswith('/') or '\\' in path:
        raise Stop('view-path', f'unsafe entry path {path!r}: absolute or backslash component')
    parts = path.split('/')
    if any(p in ('', '.', '..') for p in parts):
        raise Stop('view-path', f'unsafe entry path {path!r}: empty or parent-hop component')
    renamed = _is_harness_instruction(path)
    stored_rel = path + SRC_SUFFIX if renamed else path
    target = (view_dir / stored_rel).resolve()
    try:
        target.relative_to(view_dir.resolve())
    except ValueError as exc:
        raise Stop('view-path', f'entry path {path!r} escapes the view directory') from exc
    return stored_rel, target, renamed


def _extended_path(text):
    r"""`text`, an absolute Windows path, in its extended-length form: `\\?\<drive path>`, or
    `\\?\UNC\<server\share...>` for a UNC path. An already-extended path is returned unchanged."""
    if text.startswith('\\\\?\\'):
        return text
    if text.startswith('\\\\'):
        return '\\\\?\\UNC\\' + text[2:]
    return '\\\\?\\' + text


def _fs_path(path):
    """The filesystem-side form of a view path: on Windows its resolved extended-length form,
    which the 260-character MAX_PATH limit does not apply to; elsewhere `path` unchanged. Never
    return it to a caller or write it to the inventory: readers use the plain path."""
    if os.name != 'nt':
        return path
    return Path(_extended_path(str(Path(path).resolve())))


def _ls_tree(commit, root):
    """Parse `git ls-tree -r -z <commit>` into (mode, gtype, oid, path) tuples."""
    proc = _git(['ls-tree', '-r', '-z', commit], root)
    if proc.returncode != 0:
        raise Stop('view-lstree', _err(proc))
    entries = []
    for record in proc.stdout.split(b'\0'):
        if not record:
            continue
        try:
            meta, raw_path = record.split(b'\t', 1)
            mode, gtype, oid = meta.decode('ascii', 'replace').split()
        except ValueError as exc:
            raise Stop('view-lstree', f'unparseable ls-tree record {record[:80]!r}') from exc
        entries.append((mode, gtype, oid, raw_path.decode('utf-8', 'replace')))
    return entries


def _cat_file_batch(oids, root):
    """Materialize blob bytes for `oids`, in order, via one `git cat-file --batch` call.
    Fail-closed on a missing object or a malformed batch stream (issue #851 AC8 failed-read)."""
    if not oids:
        return []
    query = ('\n'.join(oids) + '\n').encode('ascii')
    proc = subprocess.run(
        ['git', 'cat-file', '--batch'], cwd=root, input=query,
        capture_output=True, check=False,
        env={**os.environ, 'GIT_TERMINAL_PROMPT': '0'})
    if proc.returncode != 0:
        raise Stop('view-catfile', _err(proc))
    out, pos, blobs = proc.stdout, 0, []
    for oid in oids:
        nl = out.find(b'\n', pos)
        if nl == -1:
            raise Stop('view-catfile', f'batch stream ended before the header for {oid}')
        header = out[pos:nl].decode('ascii', 'replace').split()
        if len(header) == 2 and header[1] in ('missing', 'ambiguous'):
            raise Stop('view-catfile', f'object {header[0]} is {header[1]}')
        if len(header) != 3 or not header[2].isdigit():
            raise Stop('view-catfile', f'malformed batch header {out[pos:nl][:80]!r}')
        size = int(header[2])
        start = nl + 1
        if start + size > len(out):
            raise Stop('view-catfile', f'batch stream truncated reading {oid}')
        blobs.append(out[start:start + size])
        pos = start + size + 1  # skip the trailing newline the batch format appends
    return blobs


def _deleted_entries(diff_base, commit, root):
    """Paths present at `diff_base` but absent at `commit` (status D, and the source path of a
    rename R, of `git diff --name-status diff_base commit`), recorded so a legitimately-deleted
    path is distinguishable from an unread one (issue #851 AC8)."""
    proc = _git(['diff', '--name-status', '-z', diff_base, commit], root)
    if proc.returncode != 0:
        raise Stop('view-lstree', f'diff for deleted-path detection failed: {_err(proc)}')
    fields = proc.stdout.split(b'\0')
    deleted, i = [], 0
    while i < len(fields) and fields[i]:
        status = fields[i].decode('ascii', 'replace')
        take = 2 if status[:1] in ('R', 'C') else 1
        paths = [f.decode('utf-8', 'replace') for f in fields[i + 1:i + 1 + take]]
        if len(paths) != take:
            raise Stop('view-lstree', 'name-status output ended inside a record')
        # A deletion (D) and a rename source (R paths[0]) are present at diff_base and absent
        # at the commit — proven-absent, distinct from an unread path. A copy (C) keeps its
        # source, so a C source is not absent and is not recorded.
        if status[:1] == 'D' or status[:1] == 'R':
            deleted.append(paths[0])
        i += 1 + take
    return deleted


def _inventory_text(inventory):
    """One `entries` object per line. Keep json.dumps' default separators, insertion key order
    and ensure_ascii=False: verifiers grep the literal `"path": "<p>", "stored_path": null,
    "kind": "deleted"`, so sort_keys, compact separators or ASCII escaping breaks that lookup."""
    head = json.dumps({k: v for k, v in inventory.items() if k != 'entries'}, ensure_ascii=False)[:-1]
    rows = ',\n'.join(json.dumps(e, ensure_ascii=False) for e in inventory['entries'])
    return head + (', ' if len(head) > 1 else '') + '"entries": [\n' + rows + '\n]}\n'


def _view_materialize(args):
    root = _repo_root()
    if args.revision not in ('head', 'base'):
        raise Stop('view-arguments', "--revision is head|base")
    run_dir = Path(args.run_dir)
    if not run_dir.is_absolute():
        run_dir = root / run_dir
    # Resolve the commit; one PR-head fetch retry before declaring it unavailable (AC8).
    pin = _git(['rev-parse', '--verify', f'{args.commit}^{{commit}}'], root)
    commit = pin.stdout.decode('ascii', 'replace').strip()
    if pin.returncode != 0 or not HEX40_RE.match(commit):
        if args.pr and args.pr.isdigit():
            _git(['fetch', 'origin', f'refs/pull/{args.pr}/head'], root)
            pin = _git(['rev-parse', '--verify', f'{args.commit}^{{commit}}'], root)
            commit = pin.stdout.decode('ascii', 'replace').strip()
        if pin.returncode != 0 or not HEX40_RE.match(commit):
            raise Stop('view-commit', f'commit {args.commit!r} is unavailable: {_err(pin)}')

    view_dir = run_dir / f'view-{args.revision}'
    # Every filesystem operation below goes through the _fs_path form; a plain path past
    # MAX_PATH fails on Windows, and a plain `exists()`/`rmtree` there is silently blind to it.
    fs_run_dir = _fs_path(run_dir)
    fs_view_dir = fs_run_dir / f'view-{args.revision}'
    tmp_dir = fs_run_dir / f'view-{args.revision}.tmp'
    try:
        fs_run_dir.mkdir(parents=True, exist_ok=True)
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir)
        tmp_dir.mkdir()
        raw_entries = _ls_tree(commit, root)
        blob_oids = [oid for mode, gtype, oid, _ in raw_entries
                     if gtype == 'blob' and mode != GIT_MODE_SYMLINK]
        blobs = _cat_file_batch(blob_oids, root)
        blob_iter = iter(blobs)
        inventory_entries, total_bytes, too_long = [], 0, 0
        for mode, gtype, oid, path in raw_entries:
            if mode == GIT_MODE_SUBMODULE or gtype == 'commit':
                inventory_entries.append({'path': path, 'stored_path': None,
                                          'kind': 'submodule', 'size': None, 'sha': oid})
                continue
            stored_rel, target, renamed = _safe_view_path(path, tmp_dir)
            if mode == GIT_MODE_SYMLINK:
                # Recorded, never written as a followable link (AC8 unsafe-path).
                inventory_entries.append({'path': path, 'stored_path': None,
                                          'kind': 'symlink', 'size': None, 'sha': oid})
                continue
            try:
                content = next(blob_iter)
            except StopIteration:
                # cat-file returned fewer blobs than ls-tree listed a blob oid for: an
                # oid/entry skew. Fail closed rather than let StopIteration escape both
                # main() handlers into a fail-open 'no JSON' (capability-absent) read.
                raise Stop('view-catfile', 'cat-file returned fewer blobs than ls-tree '
                                           'listed blob oids (oid/entry skew)') from None
            kind = 'lfs-pointer' if content.startswith(LFS_POINTER_PREFIX) else 'blob'
            # One try covers the parent mkdir and the write: ENAMETOOLONG from either records the
            # entry unwritten and the view goes on; any other OSError still stops as view-write.
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                # Two entries must never materialize to one file: a harness `.src` rename can
                # collide with a really-tracked `<name>.src` blob, and the later write_bytes would
                # clobber the earlier — a silent wrong-bytes read in the evidence path. Key the
                # check on the consumer's own namespace (the filesystem target), not a re-derived
                # string, so a case-fold collision on a case-insensitive filesystem is caught too:
                # tmp_dir starts empty, so an already-existing target means a prior entry wrote it
                # this run. Fail closed rather than materialize an ambiguous view (AC8).
                if target.exists():
                    raise Stop('view-path', f'stored path {stored_rel!r} collides with an already-'
                                            f'materialized entry (a harness .src rename may collide '
                                            f'with a real .src blob)')
                target.write_bytes(content)
            except OSError as exc:
                if exc.errno != errno.ENAMETOOLONG:
                    raise Stop('view-write', f'could not write {stored_rel}: {exc}') from exc
                too_long += 1
                inventory_entries.append({'path': path, 'stored_path': None,
                                          'kind': 'path-too-long', 'size': None, 'sha': oid})
                continue
            total_bytes += len(content)
            entry = {'path': path, 'stored_path': stored_rel, 'kind': kind,
                     'size': len(content), 'sha': oid}
            if renamed:
                entry['original_path'] = path
            inventory_entries.append(entry)
        if args.diff_base:
            present = {e['path'] for e in inventory_entries}
            for path in _deleted_entries(args.diff_base, commit, root):
                if path not in present:
                    inventory_entries.append({'path': path, 'stored_path': None,
                                              'kind': 'deleted', 'size': None, 'sha': None})
        harness_renamed = {e['path']: e['stored_path'] for e in inventory_entries
                           if e.get('original_path')}
        blob_count = sum(1 for e in inventory_entries if e['kind'] in ('blob', 'lfs-pointer'))
        inventory = {'revision': commit, 'entries': inventory_entries,
                     'harness_renamed': harness_renamed, 'file_count': blob_count,
                     'bytes': total_bytes}
        # _write_atomic claims both names (its sibling .tmp first): a materialized blob at either
        # would be silently overwritten, a directory an opaque 'filesystem' stop. Keep this check
        # here, not in _write_atomic, whose other callers overwrite on purpose.
        for claimed in ('inventory.json.tmp', 'inventory.json'):
            if (tmp_dir / claimed).exists():
                raise Stop('view-path', f'stored path {claimed!r} collides with the view manifest '
                                        f'write (a tracked root {claimed} cannot be materialized)')
        _write_atomic(tmp_dir / 'inventory.json', _inventory_text(inventory))
        # Swap the complete tmp tree into place atomically: a consumer sees either no view
        # directory or a whole one, never a half-materialized tree (AC8 partial-materialization).
        if fs_view_dir.exists():
            shutil.rmtree(fs_view_dir)
        os.replace(tmp_dir, fs_view_dir)
    except (Stop, OSError) as exc:
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except OSError:
            pass
        if isinstance(exc, Stop):
            raise
        raise Stop('view-write', str(exc)) from exc
    rel = view_dir.relative_to(root).as_posix() if view_dir.is_relative_to(root) else view_dir.as_posix()
    sys.stderr.write(f'view-materialize: revision={commit} file_count={blob_count} bytes={total_bytes} '
                     f'path_too_long={too_long}\n')
    return {'status': 'ok', 'revision': commit, 'view_dir': rel,
            'inventory_path': f'{rel}/inventory.json', 'file_count': blob_count,
            'bytes': total_bytes, 'path_too_long_count': too_long}


def cmd_view_materialize(args):
    _emit(_view_materialize(args))
    return 0


def build_parser():
    parser = argparse.ArgumentParser(prog='review-engine-io.py', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    prep = sub.add_parser('setup-prepare')
    prep.add_argument('--mode', required=True, choices=('head-override', 'current-branch'))
    prep.add_argument('--run-id', required=True)
    prep.add_argument('--base-branch', required=True)
    prep.add_argument('--base-sha', default='')
    prep.add_argument('--configured-base', default='')
    prep.add_argument('--pr', default='')
    prep.add_argument('--slug', default='')
    prep.add_argument('--engine-dir', default='')
    prep.add_argument('--identity-hashes', nargs='*', default=[])
    prep.set_defaults(func=cmd_setup_prepare)
    emit = sub.add_parser('setup-emit')
    emit.add_argument('--record', required=True)
    emit.add_argument('--snapshot-oid', default='')
    emit.set_defaults(func=cmd_setup_emit)
    ret = sub.add_parser('return')
    ret.add_argument('--run-dir', required=True)
    ret.add_argument('--entry', required=True)
    ret.add_argument('--iteration', required=True)
    ret.add_argument('--authored', required=True)
    ret.add_argument('--head', required=True)
    ret.add_argument('--no-checklist', action='store_true')
    ret.set_defaults(func=cmd_return)
    view = sub.add_parser('view-materialize')
    view.add_argument('--run-dir', required=True)
    view.add_argument('--revision', required=True, choices=('head', 'base'))
    view.add_argument('--commit', required=True)
    view.add_argument('--pr', default='')
    view.add_argument('--diff-base', default='')
    view.set_defaults(func=cmd_view_materialize)
    return parser


def _force_utf8_streams():
    # A non-ASCII path in the result JSON must print, not raise, on a non-UTF-8 locale.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def main(argv=None):
    _force_utf8_streams()
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except Stop as stop:
        _emit({'status': 'error', 'step': stop.step, 'reason': stop.reason})
        return 1
    except OSError as exc:
        _emit({'status': 'error', 'step': 'filesystem', 'reason': str(exc)})
        return 1


if __name__ == '__main__':
    sys.exit(main())
