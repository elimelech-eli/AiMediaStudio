"""Optional, hash-pinned image weights under <model_root>/image_gen/.

Downloads use the engine's source ranking, proxy policy and resumable transfers.
Status reads verification stamps without hashing gigabytes. Repair hashes every
file and retains mismatches; removal touches only unchanged files we created.
Installer.start('install', background=True) yields to the existing engine lease
or an optional busy callback. The CLI writes atomic, read-only status snapshots.
"""
from collections import deque
from contextlib import ExitStack, contextmanager
import json
import logging
from pathlib import Path, PurePosixPath
import re
import signal
import sys
import threading
import time
from urllib.parse import urlsplit

from .. import disk_space, model_repair, network, provision
from ..locking import runtime_lock
from ..monitoring import save

LEDGER = 'download-verified.json'
OWNERSHIP = 'owned-files.json'
RESERVE = 256 * 2**20
FAMILY = 'image-models'
BACKGROUND_RESERVE = 2 * 2**30
GENERATION_POLL_SECONDS = .25
GENERATION_RESUME_SECONDS = 10.
# Asking ComfyUI whether it is busy can take seconds (a closed port on Windows
# refuses only after about 2 s), and hashing checks once per 4 MiB block. Ask at
# most every 2 s, and a slow answer waits four times its own cost before the next.
GENERATION_PROBE_SECONDS = 2.
GENERATION_PROBE_COST_FACTOR = 4
SPEED_WINDOW_SECONDS = 10.
STATUS_INTERVAL_SECONDS = .25
OFFLINE_TRANSFER_REASONS = frozenset(('curl-5', 'curl-6', 'curl-7'))


class PackError(Exception):
    def __init__(self, reason, **details):
        super().__init__(reason)
        self.reason = reason
        self.details = details


class _GenerationPause(Exception):
    """Unwind the transfer so curl is stopped before waiting for generation."""


class _Background:
    def __init__(self, installer, stop):
        self.installer, self.stop = installer, stop
        self.resume_at = None
        self.paused = False
        self.probed_at, self.probe_gap, self.busy_seen = None, 0., False

    def generating(self):
        if self.installer.generation_busy:
            if self.probed_at is None or time.monotonic() - self.probed_at >= self.probe_gap:
                began = time.monotonic()
                self.busy_seen = bool(self.installer.generation_busy())
                self.probed_at = time.monotonic()
                self.probe_gap = max(GENERATION_PROBE_SECONDS,
                                     GENERATION_PROBE_COST_FACTOR * (self.probed_at - began))
            if self.busy_seen:
                return True
        # Probe the existing lease exclusively, without borrowing an inherited
        # descriptor. This also detects shared device work. Release immediately:
        # downloads never hold engine.lock or delay a generation acquiring it.
        # A holder is the only cross-process signal; non-generation holders also
        # cause a conservative pause. In-process callers can supply busy().
        path = (Path(self.installer.engine_root) / 'engine.lock'
                if self.installer.engine_root is not None else None)
        try:
            with runtime_lock(path, inherit=False):
                return False
        except BlockingIOError:
            return True

    def check(self):
        if self.stop.is_set():
            raise InterruptedError('cancelled')
        if self.generating():
            self.paused = True
            self.resume_at = None
            raise _GenerationPause()

    def wait(self):
        while True:
            try:
                self.check()
            except _GenerationPause:
                pass
            else:
                if self.paused and self.resume_at is None:
                    self.resume_at = time.monotonic() + GENERATION_RESUME_SECONDS
                if not self.paused or time.monotonic() >= self.resume_at:
                    self.resume_at = None
                    self.paused = False
                    self.installer._set(state='running', reason=None)
                    return
            # Reached only after the active transfer has been reaped, or at an
            # in-process checkpoint, so paused really means no active download.
            self.installer._set(state='paused_for_generation', reason='busy_video')
            self.stop.wait(GENERATION_POLL_SECONDS)


def catalog():
    spec = json.loads(Path(__file__).with_name('image_models.json').read_text(encoding='utf-8'))
    validate_catalog(spec)
    return spec


def _relative(name):
    if (not isinstance(name, str) or not name or '\\' in name or ':' in name
            or name.startswith('/') or any(p in ('', '.', '..') for p in name.split('/'))):
        raise PackError('invalid_catalog')
    return PurePosixPath(name)


def validate_catalog(spec):
    try:
        if (spec['format'] != 1 or spec['family'] != 'image' or not spec['model_id']
                or not isinstance(spec['repo'], str) or not spec['repo']
                or not isinstance(spec['revision'], str) or not spec['revision']):
            raise PackError('invalid_catalog')
        found = spec['groups']['image']
        if not found or len({r['file'] for r in found}) != len(found):
            raise PackError('invalid_catalog')
        for row in found:
            _relative(row['file'])
            if (type(row['bytes']) is not int or row['bytes'] <= 0
                    or not re.fullmatch('[0-9a-f]{64}', row['sha256'])
                    or row['component'] not in ('dit', 'text_encoder', 'vae', 'text_encoder_config', 'processor')):
                raise PackError('invalid_catalog')
            ids = [s['id'] for s in row['sources']]
            if (len(set(ids)) != len(ids) or not {'official', 'modelscope'} <= set(ids)
                    or not set(ids) <= {'official', 'modelscope', 'hf-mirror'}):
                raise PackError('invalid_catalog')
            for source in row['sources']:
                url = urlsplit(source['url'])
                if url.scheme not in ('https', 'http') or not url.netloc or url.username or url.password:
                    raise PackError('invalid_catalog')
    except (KeyError, TypeError, ValueError) as error:
        raise PackError('invalid_catalog') from error


def rows(spec=None):
    spec = spec if spec is not None else catalog()
    validate_catalog(spec)
    return [dict(row, family='image', model_id=spec['model_id'], repo=spec['repo'], revision=spec['revision'])
            for row in spec['groups']['image']]


def base(root=None):
    if root is None:
        from ..paths import installed_model_root
        root = installed_model_root()
    return Path(root).expanduser().absolute() / 'image_gen'


def _path(folder, name):
    """Refuse links at the pack root or below it, including partials/receipts."""
    relative = _relative(name)
    path = folder
    if path.is_symlink():
        raise PackError('unsafe_path')
    for part in relative.parts:
        path /= part
        if path.is_symlink():
            raise PackError('unsafe_path')
    return path


def target(row, root=None):
    return _path(base(root), row['file'])


def _read(folder, name):
    try:
        value = json.loads(_path(folder, name).read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _intact(path, row, ledger):
    try:
        prior = ledger.get(str(path), {})
        return path.is_file() and path.stat().st_size == row['bytes'] and isinstance(prior, dict) and all(
            prior.get(k) == v for k, v in provision.file_identity(path, row).items())
    except OSError:
        return False


def _owned_intact(path, stamp):
    return path.is_file() and isinstance(stamp, dict) and all(
        stamp.get(k) == v for k, v in provision.file_identity(path, stamp).items())


# The notice written next to the weights. The text lives here; licenses/NOTICE.txt carries the same words
# for people reading the source and is never needed at run time.
NOTICE_TEXT = (b'Qwen is licensed under the Qwen RESEARCH LICENSE AGREEMENT, Copyright (c) 2026 Hangzhou Tongyi '
               b'Laboratory Technology Co., Ltd. All Rights Reserved.\n')


def _notice():
    return NOTICE_TEXT


def _notice_ready(path):
    """Informational only: a missing or different notice never makes the pack unusable."""
    try:
        return path.is_file() and path.read_bytes() == NOTICE_TEXT
    except OSError:
        return False


def _write_notice(folder, owned):
    """Put the notice into the model folder when possible; a failure is logged and the install goes on."""
    notice = _path(folder, 'NOTICE.txt')
    try:
        if notice.exists():
            return   # present (ours or the user's own text): left as it is
        notice.write_bytes(NOTICE_TEXT)
        _own(folder, owned, notice)
    except Exception as error:
        logging.warning('[FreeVideo] Could not write the image model notice: %s', error)


def status(root=None):
    """Missing files and unique retained bytes; no network or full weight reads."""
    folder = base(root)
    ledger = _read(folder, LEDGER)
    files, missing, downloaded, verified_bytes = [], [], 0, 0
    for row in rows():
        path = target(row, root)
        intact = _intact(path, row, ledger)
        size = path.stat().st_size if path.is_file() else 0
        part = _path(folder, row['file'] + '.partial')
        partial = part.stat().st_size if part.is_file() else 0
        retained = row['bytes'] if intact else min(row['bytes'], max(size, partial))
        downloaded += retained
        verified_bytes += row['bytes'] if intact else 0
        if not intact:
            missing.append(row['file'])
        files.append(dict(file=row['file'], bytes=row['bytes'], ready=intact, downloaded_bytes=retained))
    notice = _path(folder, 'NOTICE.txt')
    notice_ready = _notice_ready(notice)
    total = sum(r['bytes'] for r in files)
    available = not missing
    return dict(installable=True, ready=available, total_bytes=total, verified_bytes=verified_bytes,
                downloaded_bytes=downloaded, bytes=sum(r['bytes'] for r in files if not r['ready']),
                remaining_bytes=sum(r['bytes'] - r['downloaded_bytes'] for r in files if not r['ready']),
                missing=missing, notice_ready=notice_ready, files=files,
                state='ready' if available else 'partial' if downloaded else 'missing')


def ready(root=None):
    return status(root)['ready']


@contextmanager
def _lease(root, engine_root=None, destructive=False):
    if root is None and engine_root is None:
        from ..paths import data_root
        engine_root = data_root()
    folder = base(root)
    _path(folder, 'pack.lock')
    _path(folder, 'logs/model-mismatches.json')
    with ExitStack() as stack:
        if engine_root is not None:
            engine = Path(engine_root)
            stack.enter_context(runtime_lock(engine / 'setup.lock', inherit=False))
            if destructive:
                stack.enter_context(runtime_lock(engine / 'engine.lock', inherit=False))
                stack.enter_context(runtime_lock(engine / 'launcher/host-setup.lock', inherit=False))
        stack.enter_context(runtime_lock(folder / 'pack.lock', inherit=False))
        yield folder


def verify(root=None, progress=None, check=None):
    """Explicit full integrity check; bad stamps are discarded, files are kept."""
    with _lease(root) as folder:
        _verify(folder, root, progress or (lambda v: None), check or (lambda: None), full=True)
        return status(root)


def _verify(folder, root, progress, check, full=False):
    ledger = _read(folder, LEDGER)
    todo = []
    total = sum(r['bytes'] for r in rows())
    done = 0
    for row in rows():
        check()
        path = target(row, root)
        def checked(current, size):
            check()
            progress(dict(phase='verify', done=done + current, total=total))
        before = model_repair.identity(path)
        if not provision.verified(path, row, ledger, mode='full' if full else 'auto', progress=checked):
            ledger.pop(str(path), None)
            if path.exists():
                model_repair.record(folder, path, row, before)
            todo.append(row)
        done += row['bytes']
    save(_path(folder, LEDGER), ledger)
    return ledger, todo


def _download_plan(engine_root=None):
    from ..adaln_assets import _download_plan as installed
    plan = installed(engine_root)
    plan = dict(plan, sources={k: [dict(r) for r in v] for k, v in plan.get('sources', {}).items()})
    # Older installations measured these same hosts for video weights. Keep
    # that measured ranking until an image-specific probe is available.
    if FAMILY not in plan['sources']:
        inherited = plan['sources'].get('vdn-models', [])
        plan['sources'][FAMILY] = [dict(r) for r in inherited if r['id'] in ('official', 'modelscope', 'hf-mirror')]
    known = {r['id'] for r in plan['sources'][FAMILY]}
    plan['sources'][FAMILY] += [dict(id=s) for s in ('official', 'hf-mirror', 'modelscope') if s not in known]
    return plan


def _own(folder, owned, path, row=None):
    owned[path.relative_to(folder).as_posix()] = provision.file_identity(path, row or {})
    save(_path(folder, OWNERSHIP), owned)


def _transfer(plan, row, path, progress, check, background=None):
    from ..download_settings import current, SwitchRequested
    failures = []
    if background is not None:
        plan = dict(plan)
        prior_event = plan.get('event_callback')
        def event(value):
            if value.get('action') in ('fallback', 'route-retry'):
                failures.append((value.get('reason'), value.get('http_status')))
            if prior_event:
                prior_event(value)
        plan['event_callback'] = event
    while True:
        if background is not None:
            background.wait()
        settings = current(plan)
        # An explicit choice supersedes affinity to the old partial's source.
        plan['manual_source_switch'] = settings['source'] in ('official', 'hf-mirror', 'modelscope')
        def resource_check():
            check()
            latest = current(plan)
            if any(latest[k] != settings[k] for k in ('source', 'proxy_mode')):
                raise SwitchRequested(latest)
        plan['resource_check'] = resource_check
        try:
            network.download(network.model_urls(plan, row), path, row['sha256'], progress,
                             network=plan, size=row['bytes'], category=FAMILY,
                             keep_partial=True, stall_seconds=30)
            return
        except SwitchRequested:
            if background is None:
                check()  # Resume with the newly selected policy.
        except _GenerationPause:
            # network.download's finally terminates/reaps curl, retaining the
            # partial and source affinity. The next attempt uses its Range.
            if background is None:
                raise
        except ConnectionError as error:
            if background is None:
                raise
            raise PackError('offline') from error
        except RuntimeError as error:
            if background is None:
                raise
            offline = failures and all(reason in OFFLINE_TRANSFER_REASONS and
                                       status in (None, '', '000') for reason, status in failures)
            raise PackError('offline' if offline else 'source_failed') from error


def install(root=None, progress=None, check=None, *, engine_root=None, repair=False, _background=None):
    """Install only missing weights. Repair also hashes and retains bad originals."""
    progress = progress or (lambda v: None)
    check = check or (lambda: None)
    transfer_check = _background.check if _background is not None else check
    try:
        with _lease(root, engine_root, destructive=repair) as folder:
            ledger, todo = _verify(folder, root, progress, check, full=repair)
            total = sum(r['bytes'] for r in todo)
            retained = 0
            for row in todo:
                partial = _path(folder, row['file'] + '.partial')
                if partial.is_file() and partial.stat().st_size < row['bytes']:
                    retained += partial.stat().st_size
            reserve = BACKGROUND_RESERVE if _background is not None else RESERVE
            needed = total - retained + reserve
            free = disk_space.free_bytes(folder)
            if total and free < needed:
                raise PackError('disk_space', needed_bytes=needed, free_bytes=free)
            plan = _download_plan(engine_root)
            plan.update(quiet=True, resource_check=check)
            owned = _read(folder, OWNERSHIP)
            _write_notice(folder, owned)
            done = 0
            pending_prefixes = 0
            if _background is not None:
                done = sum(r['bytes'] for r in rows()) - total
                total += done
                pending_prefixes = sum(min(row['bytes'], _path(folder, row['file'] + '.partial').stat().st_size)
                                       for row in todo if _path(folder, row['file'] + '.partial').is_file())
                progress(dict(phase='download', done=done + pending_prefixes, total=total))
            for row in todo:
                check()
                path = target(row, root)
                if path.exists():
                    if not repair:
                        raise PackError('needs_repair')
                    approved = model_repair.replacement(path, row, model_repair.read(folder), set())
                    if approved is None:
                        raise PackError('changed')
                    model_repair.retain(folder, path, approved)
                    owned.pop(row['file'], None)
                    save(_path(folder, OWNERSHIP), owned)
                partial = _path(folder, row['file'] + '.partial')
                if _background is not None and partial.is_file():
                    pending_prefixes -= min(row['bytes'], partial.stat().st_size)
                affinity = _path(folder, row['file'] + '.partial.source.json')
                may_own = {p: not p.exists() or _owned_intact(p, owned.get(p.relative_to(folder).as_posix()))
                           for p in (partial, affinity)}
                def moved(current, size, speed, **kwargs):
                    progress(dict(phase='download', done=done + current + pending_prefixes, total=total))
                    transfer_check()
                try:
                    _transfer(plan, row, path, moved, transfer_check, _background)
                finally:
                    # Completed files and cancellable prefixes have separate identities.
                    for artifact in (partial, affinity):
                        if may_own[artifact] and _path(folder, artifact.relative_to(folder).as_posix()).is_file():
                            _own(folder, owned, artifact)
                ledger[str(path)] = provision.file_identity(path, row)
                save(_path(folder, LEDGER), ledger)
                _own(folder, owned, path, row)
                done += row['bytes']
                progress(dict(phase='download', done=done + pending_prefixes, total=total))
            check()
            return status(root)
    except (PackError, InterruptedError):
        raise
    except BlockingIOError as error:
        raise PackError('busy') from error
    except Exception as error:
        raise PackError('download_failed') from error


def repair(root=None, progress=None, check=None, *, engine_root=None):
    return install(root, progress, check, engine_root=engine_root, repair=True)


def removal_plan(root=None):
    folder = base(root)
    owned = _read(folder, OWNERSHIP)
    allowed = {'NOTICE.txt'}
    for row in rows():
        allowed.update((row['file'], row['file'] + '.partial', row['file'] + '.partial.source.json'))
    for name in allowed:
        _path(folder, name)
    files, skipped = [], []
    for name, stamp in owned.items():
        if name not in allowed or not isinstance(stamp, dict):
            continue
        path = _path(folder, name)
        if not path.exists():
            continue
        if _owned_intact(path, stamp):
            files.append(dict(file=name, identity=stamp, bytes=path.stat().st_size))
        else:
            skipped.append(name)
    return dict(files=files, bytes=sum(f['bytes'] for f in files), skipped=skipped)


def remove(root=None, check=None, *, engine_root=None):
    """Delete our unchanged downloads/partials/notice; keep imports and repairs."""
    check = check or (lambda: None)
    try:
        with _lease(root, engine_root, destructive=True) as folder:
            plan = removal_plan(root)
            owned, ledger = _read(folder, OWNERSHIP), _read(folder, LEDGER)
            released, removed = 0, []
            for entry in plan['files']:
                check()
                path = _path(folder, entry['file'])
                stamp = entry['identity']
                if not _owned_intact(path, stamp):
                    plan['skipped'].append(entry['file'])
                    continue
                path.unlink()
                removed.append(entry['file'])
                released += entry['bytes']
                owned.pop(entry['file'], None)
                ledger.pop(str(path), None)
                save(_path(folder, OWNERSHIP), owned)
                save(_path(folder, LEDGER), ledger)
            return dict(released_bytes=released, removed=removed, skipped=plan['skipped'])
    except BlockingIOError as error:
        raise PackError('busy') from error


class Installer:
    """One background action per pack; cancel keeps completed files and prefixes."""
    def __init__(self, root=None, *, engine_root=None, busy=None):
        self.root, self.engine_root = root, engine_root
        self.generation_busy = busy
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.thread = None
        self.value = dict(state='idle', done=0, total=0, bytes_per_second=0, reason=None)
        self.samples = deque()
        self.transferred = 0
        self.last_done = None
        self.background = False

    @property
    def busy(self):
        return self.thread is not None and self.thread.is_alive()

    def state(self):
        with self.lock:
            return dict(self.value, bytes_per_second=self._rate(time.monotonic()))

    def _rate(self, now):
        if self.value['state'] != 'running' or not self.samples:
            return 0
        cutoff = now - SPEED_WINDOW_SECONDS
        while len(self.samples) > 1 and self.samples[1][0] <= cutoff:
            self.samples.popleft()
        start, amount = self.samples[0]
        if start < cutoff:
            if len(self.samples) > 1:
                end, next_amount = self.samples[1]
                amount += (next_amount - amount) * (cutoff - start) / (end - start)
            else:
                amount = self.transferred
            start = cutoff
        return max(0, self.transferred - amount) / (now - start) if now > start else 0

    def _progress(self, value):
        value = dict(value)
        with self.lock:
            if value.get('phase') == 'download':
                now, done = time.monotonic(), value['done']
                if self.last_done is not None:
                    self.transferred += max(0, done - self.last_done)
                self.last_done = done
                if not self.samples or now > self.samples[-1][0]:
                    self.samples.append((now, self.transferred))
                self.value.update(bytes_per_second=self._rate(now))
            elif self.background:
                # Verification byte counts measure hashing, not downloaded bytes.
                value.pop('done', None)
                value.pop('total', None)
        self._set(**value)

    def _set(self, **value):
        with self.lock:
            if 'state' in value and value['state'] != self.value['state'] and self.samples:
                self.samples.append((time.monotonic(), self.transferred))
            self.value.update(value)

    def start(self, action='install', *, background=False):
        if action not in ('install', 'repair', 'remove', 'verify'):
            raise ValueError('Unknown image pack action')
        if background and action != 'install':
            raise ValueError('Background mode is only available for install')
        with self.lock:
            if self.busy:
                return dict(self.value)
            self.stop = threading.Event()
            self.background = background
            self.samples.clear()
            self.transferred, self.last_done = 0, None
            self.value = dict(state='running', action=action, done=0, total=0, bytes_per_second=0, reason=None)
            self.thread = threading.Thread(target=self._run, args=(action, self.stop, background),
                                           name='freevideo-image-pack', daemon=True)
            self.thread.start()
            return dict(self.value)

    def cancel(self):
        self.stop.set()
        return self.state()

    def _run(self, action, stop, background):
        def check():
            if stop.is_set():
                raise InterruptedError('cancelled')
        try:
            control = _Background(self, stop) if background else None
            if background:
                initial = status(self.root)
                self._set(done=initial['downloaded_bytes'], total=initial['total_bytes'])
            options = dict(root=self.root, check=control.wait if control else check)
            if control:
                options['_background'] = control
            if action != 'verify':
                options['engine_root'] = self.engine_root
            if action != 'remove':
                options['progress'] = self._progress
            result = globals()[action](**options)
            check()
            if background:
                self._set(done=result['total_bytes'], total=result['total_bytes'])
            self._set(state='done', reason=None, result=result)
        except InterruptedError:
            self._set(state='cancelled', reason=None)
        except PackError as error:
            reason = error.reason
            if background and reason not in ('disk_space', 'offline', 'source_failed', 'busy_video', 'failed'):
                reason = 'source_failed' if reason == 'download_failed' else 'failed'
            self._set(state='failed', reason=reason, **error.details)
        except Exception:
            self._set(state='failed', reason='failed')


def main(argv=None):
    """Download worker and read-only status reader for installer/launcher callers."""
    import argparse
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == '--status':
        argv[0] = 'status'
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    download = commands.add_parser('download')
    download.add_argument('--background', action='store_true')
    download.add_argument('--root', type=Path)
    download.add_argument('--engine-root', type=Path)
    download.add_argument('--status-file', type=Path, required=True)
    reader = commands.add_parser('status')
    reader.add_argument('--status-file', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == 'status':
        try:
            sys.stdout.write(args.status_file.read_text(encoding='utf-8'))
            return 0
        except OSError:
            print('Image pack status is unavailable.', file=sys.stderr)
            return 1

    installer = Installer(args.root, engine_root=args.engine_root)
    received = threading.Event()
    def cancelled(signum, frame):
        received.set()
        # A signal can interrupt state() while its lock is held in this thread.
        # Set only the cancellation event here; the worker publishes the state.
        installer.stop.set()
    handlers = {}
    try:
        for name in ('SIGTERM', 'SIGBREAK', 'SIGINT'):
            if hasattr(signal, name):
                signum = getattr(signal, name)
                handlers[signum] = signal.signal(signum, cancelled)
        installer.start('install', background=args.background)
        if received.is_set():
            installer.cancel()
        while True:
            save(args.status_file, dict(installer.state(), updated_at=time.time()))
            if not installer.busy:
                # The thread may finish between snapshotting and checking busy.
                save(args.status_file, dict(installer.state(), updated_at=time.time()))
                return 0 if installer.state()['state'] == 'done' and not received.is_set() else 1
            installer.thread.join(STATUS_INTERVAL_SECONDS)
    except OSError:
        print('Could not update image pack status.', file=sys.stderr)
        return 1
    finally:
        if installer.busy:
            installer.cancel()
            installer.thread.join()
        for signum, handler in handlers.items():
            signal.signal(signum, handler)


if __name__ == '__main__':
    raise SystemExit(main())
