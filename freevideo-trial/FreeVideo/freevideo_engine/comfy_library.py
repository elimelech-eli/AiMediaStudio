"""Browse completed FreeVideo outputs across ComfyUI/browser restarts."""
import asyncio
from contextlib import nullcontext
import io
import json
import logging
import os
import re
import stat
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from .agent import enabled as agent_enabled
from .comfy_assets import output_summary
from .runtime_alias import is_junction, checked_real_path, AliasUnavailable
from .long_paths import io_path, plain
from .system import windows

_ID = re.compile(r'\d{4}-\d{2}-\d{2}/[0-9a-f]{32}')


def _video(root, identity):
    if not isinstance(identity, str) or not _ID.fullmatch(identity):
        raise ValueError('Invalid saved video')
    root = Path(root).resolve()
    path = (root / 'FreeVideo' / identity / 'video.mp4').resolve()
    if not path.is_relative_to(root / 'FreeVideo'):
        raise ValueError('Saved video is outside the output folder')
    return path


def _report(path):
    # Read only the small request summary, never tensors, prompts or media.
    with path.with_suffix('.request.json').open('rb') as stream:
        data = stream.read(4 * 1024 * 1024 + 1)
    if len(data) > 4 * 1024 * 1024:
        raise ValueError('Request summary is too large')
    report = json.loads(data)
    if not isinstance(report, dict) or report.get('success') is not True:
        raise ValueError('Video is not complete')
    return report


def _agent(folder):
    """The agent job that made this run, from the small record agent requests leave in workflow.json."""
    try:
        with (folder / 'workflow.json').open('rb') as stream:
            data = stream.read(64 * 1024 + 1)
        if len(data) > 64 * 1024 or b'"freevideo_agent"' not in data:
            return None
        value = json.loads(data).get('freevideo_agent')
    except (OSError, ValueError, AttributeError):
        return None
    if not isinstance(value, dict):
        return None
    return {key: str(value[key])[:120] for key in ('job', 'label', 'project', 'client') if value.get(key)}


def list_videos(output_directory, *, before=None, limit=24):
    """Return a stable newest-first page, with only relative output paths."""
    if not 1 <= limit <= 48:
        raise ValueError('Invalid page size')
    cursor = None
    if before:
        stamp, identity = before.split(':', 1)
        if not stamp.isdigit() or not _ID.fullmatch(identity):
            raise ValueError('Invalid page cursor')
        cursor = (int(stamp), identity)
    root = Path(output_directory).resolve()
    from .comfy_chain import hidden_outputs
    hidden = hidden_outputs(root)
    candidates = []
    for path in (root / 'FreeVideo').glob('*/*/video.mp4'):
        identity = path.parent.relative_to(root / 'FreeVideo').as_posix()
        try:
            path = _video(root, identity)
            info = path.stat()
            key = (info.st_mtime_ns, identity)
            if info.st_size and (cursor is None or key < cursor):
                candidates.append((key, path, info))
        except (OSError, ValueError):
            continue
    rows = []
    for key, path, info in sorted(candidates, key=lambda item: item[0], reverse=True):
        try:
            report = _report(path)
            relative = Path('FreeVideo') / key[1] / 'video.mp4'
            if relative.as_posix() in hidden:
                continue
            summary = output_summary(report, relative)
            # Geometry may gain input metadata in future reports. Keep this API
            # an explicit allowlist, not an export of the retained report.
            summary['geometry'] = {k: v for k, v in summary['geometry'].items()
                                   if k in ('width', 'height', 'frames', 'fps', 'seconds')
                                   and type(v) in (int, float)}
            if 'encoder_file' in summary:
                # The library API exposes only relative paths.
                summary['encoder_file'] = dict(summary['encoder_file'])
                summary['encoder_file'].pop('path', None)
            if not (root / summary['report']).is_file():
                summary['report'] = None
            try:
                agent = _agent(path.parent) if agent_enabled() else None
            except Exception as error:
                # Optional attribution must not hide an otherwise valid saved video.
                logging.getLogger(__name__).warning('[FreeVideo] Agent label unavailable: %s', error)
                agent = None
            if agent:
                summary['agent'] = agent
            rows.append(dict(summary, id=key[1], bytes=info.st_size,
                             created_at=datetime.fromtimestamp(info.st_mtime, timezone.utc).isoformat(),
                             cursor=str(key[0]) + ':' + key[1]))
        except (OSError, ValueError, TypeError, AttributeError):
            # A partially written or old malformed report must not hide the
            # rest of the library or publish an unfinished generation.
            continue
        if len(rows) > limit:
            break
    more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = rows[-1]['cursor'] if more else None
    for row in rows:
        row.pop('cursor')
    return dict(items=rows, next=next_cursor)


def thumbnail(output_directory, identity):
    path = _video(output_directory, identity)
    saved = path.with_suffix('.thumbnail.jpg')
    root = Path(output_directory).resolve() / 'FreeVideo'
    def check_sidecar(sidecar):
        if sidecar.is_symlink() or not sidecar.resolve().is_relative_to(root):
            raise ValueError('Saved thumbnail sidecar is outside the library or is a symbolic link')
    check_sidecar(path.with_suffix('.request.json'))
    check_sidecar(saved)
    _report(path)
    if saved.is_file() and saved.stat().st_mtime_ns >= path.stat().st_mtime_ns:
        with os.fdopen(os.open(saved, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0)), 'rb') as stream:
            data = stream.read(512 * 1024 + 1)
        if data.startswith(b'\xff\xd8') and len(data) <= 512 * 1024:
            return data
    # CPU decoding only. Grid thumbnails must not take CUDA memory from a
    # generation, and we only decode the first frame of each requested video.
    import av
    from PIL import Image
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        stream.thread_count = 1
        image = next(container.decode(stream)).to_image()
    image.thumbnail((384, 256), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format='JPEG', quality=80)
    data = buffer.getvalue()
    check_sidecar(saved)
    try:
        with os.fdopen(os.open(saved, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, 'O_NOFOLLOW', 0)
                                | getattr(os, 'O_BINARY', 0), 0o666), 'wb') as stream:
            stream.write(data)
    except OSError:
        check_sidecar(saved)
        pass  # A read-only output directory still supports browsing.
    return data


def video_download(output_directory, identity):
    """Name a saved download without renaming the engine's retained artifacts."""
    path = _video(output_directory, identity)
    _report(path)
    info = path.stat()
    if not info.st_size:
        raise ValueError('Video is empty')
    stamp = datetime.fromtimestamp(info.st_mtime, timezone.utc).strftime('%Y%m%d_%H%M%S')
    return path, 'FreeVideo_%s_%s.mp4' % (stamp, identity.split('/')[-1][:12])


# What a FreeVideo request writes into its own run folder, including the
# prompt-enhancement record and the staging copy monitoring.save keeps when
# Windows would not let it replace a JSON record. A creation whose folder
# holds anything else, or any link, is not deleted at all.
_OWNED_FILE = re.compile(r'(?:video\.[A-Za-z0-9._-]+|prompt\.txt|workflow\.json|comfy-request\.json|generate\.log'
                         r'|continuation-source\.safetensors'
                         r'|media\.json|prompt-rewrite\.json|input-conditioning\.pt|(?:first|last)\.png'
                         r'|reference-\d{2}\.(?:png|mp4|wav))(?:\.[a-z0-9_]{8}\.tmp)?')
_OWNED_FOLDER = 'video.artifacts'
_REPARSE_POINT = 0x400


class DeleteRefused(ValueError):
    def __init__(self, reason, kept=()):
        super().__init__(reason)
        self.reason, self.kept = reason, list(kept)


def _plain(path):
    """A regular file or directory: never a symlink, junction or other reparse point."""
    info = os.lstat(path)
    if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & _REPARSE_POINT:
        return False
    return stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)


def _foreign(folder):
    """Names in a run folder that FreeVideo did not write, or that are links."""
    folder = io_path(checked_real_path(folder))
    kept = []
    for entry in sorted(folder.iterdir()):
        if not _plain(entry):
            kept.append(entry.name)
        elif entry.is_dir():
            if entry.name != _OWNED_FOLDER:
                kept.append(entry.name + '/')
                continue
            for parent, folders, files in os.walk(entry):
                for name in folders + files:
                    if not _plain(Path(parent) / name):
                        kept.append((Path(parent) / name).relative_to(folder).as_posix())
                folders[:] = [name for name in folders if not is_junction(Path(parent) / name)]
        elif not _OWNED_FILE.fullmatch(entry.name):
            kept.append(entry.name)
    return kept


def _remove(folder):
    """Remove a verified folder bottom-up; return bytes freed and paths left behind."""
    try:
        folder = io_path(checked_real_path(folder))
    except AliasUnavailable:
        return 0, [plain(folder)]
    freed, left = 0, []
    if is_junction(folder):
        return 0, [plain(folder)]
    if windows():
        # Bottom-up os.walk cannot prune before entering a Windows junction.
        # Collect a pruned listing, then keep os.walk's original bottom-up
        # sibling order when removing ordinary rows.
        rows = {}
        for parent, folders, files in os.walk(folder):
            linked = [name for name in folders if is_junction(Path(parent) / name)]
            left.extend(plain(Path(parent) / name) for name in linked)
            folders[:] = [name for name in folders if name not in linked]
            rows[Path(parent)] = (parent, folders[:], files)
        ordered, pending = [], [(Path(folder), False)]
        while pending:
            current, visited = pending.pop()
            row = rows.get(current)
            if row is None:
                continue
            if visited:
                ordered.append(row)
            else:
                pending.append((current, True))
                pending.extend((current / name, False) for name in reversed(row[1]))
        walk = ordered
    else:
        walk = os.walk(folder, topdown=False)
    for parent, folders, files in walk:
        for name in files:
            path = Path(parent) / name
            try:
                if not _plain(path):
                    left.append(plain(path)); continue
                size = path.stat().st_size
                if name == 'continuation-source.safetensors':
                    # Request snapshots are read-only while used; Windows
                    # requires clearing that flag when deleting their run.
                    path.chmod(0o600)
                path.unlink()
                freed += size
            except OSError:
                left.append(plain(path))
        for name in folders:
            try:
                (Path(parent) / name).rmdir()
            except OSError:
                left.append(plain(Path(parent) / name))
    try:
        Path(folder).rmdir()
    except OSError:
        left.append(plain(folder))
    return freed, left


# Decoded frames and audio the engine writes to build and check the MP4.
# Nothing reads them once a creation is saved: Creations, sharing and the
# workflow read the MP4, and an upscale reads the preview's first pass. The
# sampling result, conditioning and first pass stay.
_DECODED = ('rgb.npy', 'audio.npy', 'audio.wav')
_ATTEMPT = re.compile(r'\d{2}-[0-9A-Za-z_-]+')
_RELEASED = '.decoded-released.json'
# The startup release, a generation re-arming it and a library delete take
# turns, so none of them reads a folder or the marker while another writes it.
_RELEASING = threading.Lock()


def release_decoded(folder):
    """Delete a saved creation's decoded frames and audio, retried attempts' included.

    Only where the engine writes them: video.artifacts itself and its
    attempts/NN-id folders. A folder holding anything FreeVideo did not write,
    or any link, is left alone, as delete_video leaves it. Paths Windows still
    has open are listed.
    """
    try:
        folder = io_path(checked_real_path(folder))
        artifacts = folder / _OWNED_FOLDER
        if not _plain(folder) or _foreign(folder):
            return dict(freed_bytes=0, left=[], skipped='foreign-files')
        if not artifacts.is_dir():
            return dict(freed_bytes=0, left=[], skipped='no-artifacts')
        places, freed, left = [artifacts], 0, []
        try:
            if (artifacts / 'attempts').is_dir():
                places += [path for path in sorted((artifacts / 'attempts').iterdir())
                           if _ATTEMPT.fullmatch(path.name) and path.is_dir()]
        except OSError:
            left.append(_OWNED_FOLDER + '/attempts')  # retried at a later start
        for place in places:
            for name in _DECODED:
                path = place / name
                try:
                    if not _plain(path):
                        continue
                    size = path.stat().st_size
                    path.unlink()
                    freed += size
                except FileNotFoundError:
                    continue
                except OSError:
                    left.append(path.relative_to(folder).as_posix())
        return dict(freed_bytes=freed, left=left)
    except OSError:
        # Listed as left, so a later start tries the whole folder again.
        return dict(freed_bytes=0, left=['.'], skipped='unreadable')


def release_later(output_directory):
    """Have the next start finish a release that Windows kept open."""
    from .monitoring import save
    output_directory = checked_real_path(output_directory)
    with _RELEASING:
        save(Path(output_directory).resolve() / 'FreeVideo' / _RELEASED, dict(schema=1, pending=True))


def release_earlier(output_directory):
    """Once after updating, release the creations saved before completion did it.

    Only finished creations of the creative workspace, which writes
    comfy-request.json, and none that is being generated. Later starts repeat
    it while a file Windows kept open is left.
    """
    from .monitoring import save
    try:
        output_directory = checked_real_path(output_directory)
    except AliasUnavailable:
        return None
    root = Path(output_directory).resolve() / 'FreeVideo'
    marker = root / _RELEASED
    if not root.is_dir():
        return None
    with _RELEASING:
        # A marker Windows would not let save replace stays beside it as a
        # staging copy; the release it asked for is still owed.
        staged = sorted(root.glob(_RELEASED + '.*.tmp'))
        try:
            if not staged and json.loads(marker.read_text(encoding='utf-8')).get('pending') is not True:
                return None
        except (OSError, ValueError, AttributeError):
            pass
        totals = dict(videos=0, freed_bytes=0, left=0, skipped=0)
        for path in sorted(root.glob('*/*/video.mp4')):
            folder = path.parent
            try:
                if (not _ID.fullmatch(folder.relative_to(root).as_posix())
                        or not _plain(folder.parent) or not _plain(folder)):
                    continue
                _report(path)
                state = folder / 'comfy-request.json'
                if state.stat().st_size > 1024 * 1024:
                    continue
                state = json.loads(state.read_text(encoding='utf-8'))
                if not isinstance(state, dict) or state.get('status') in ('starting', 'running'):
                    continue
            except (OSError, ValueError, TypeError):
                continue
            result = release_decoded(folder)
            totals['videos'] += result['freed_bytes'] > 0
            totals['freed_bytes'] += result['freed_bytes']
            totals['left'] += len(result['left'])
            totals['skipped'] += result.get('skipped') == 'foreign-files'
        save(marker, dict(schema=1, pending=totals['left'] > 0, released_at=time.time(), **totals))
        for path in staged:
            try:
                path.unlink()
            except OSError:
                pass
    return totals


def _queued_continuation_uses(path, output_directory, queue):
    if queue is None:
        return False
    from .comfy_continuation import resolve_continue_from
    for rows in queue.get_current_queue():
        for entry in rows:
            prompt = entry[2] if isinstance(entry, (list, tuple)) and len(entry) > 2 else None
            if not isinstance(prompt, dict):
                continue
            for node in prompt.values():
                if not isinstance(node, dict) or node.get('class_type') != 'FreeVideoGenerate':
                    continue
                inputs = node.get('inputs', {})
                source = inputs.get('continue_from') if isinstance(inputs, dict) else None
                if isinstance(source, (list, tuple)):
                    # A connected path is resolved only by execution. Until
                    # then the queue can still depend on this creation.
                    return True
                if not isinstance(source, str) or not source:
                    continue
                try:
                    # Saved creations live under output; its absolute paths
                    # and relative history names share the node's resolver.
                    resolved = resolve_continue_from(source, output_directory, output_directory)
                except ValueError:
                    continue
                if Path(resolved) == path:
                    return True
    return False


def delete_video(output_directory, identity, *, queue=None):
    """Delete one saved creation: its whole run folder, only when FreeVideo wrote everything in it.

    The folder is first renamed into FreeVideo/.deleted, so it leaves the
    library at once, or, when Windows still has a file open, nothing changes.
    """
    try:
        output_directory = checked_real_path(output_directory)
    except AliasUnavailable as error:
        raise DeleteRefused('not-freevideo') from error
    path = _video(output_directory, identity)
    _report(path)
    root = Path(output_directory).resolve() / 'FreeVideo'
    folder = path.parent
    if folder.parent.parent != root or not _plain(folder.parent) or not _plain(folder):
        raise DeleteRefused('not-freevideo')
    # Not while the startup release is deleting files in this folder.
    with _RELEASING, (queue.mutex if queue is not None else nullcontext()):
        from .comfy_editor import reference_users
        try:
            users = reference_users(output_directory, identity)
        except (OSError, ValueError):
            raise DeleteRefused('editor-unavailable') from None
        if users:
            raise DeleteRefused('editor-in-use', users)
        kept = _foreign(folder)
        if kept:
            raise DeleteRefused('foreign-files', kept)
        if _queued_continuation_uses(path, output_directory, queue):
            raise DeleteRefused('continuation-in-use')
        # A second pass of this preview may be reading its first pass right now.
        for state_path in root.glob('*/*/comfy-request.json'):
            try:
                state = json.loads(state_path.read_text(encoding='utf-8')) if state_path.stat().st_size <= 1024 * 1024 else {}
            except (OSError, ValueError):
                continue
            if not isinstance(state, dict) or state.get('status') not in ('queued', 'starting', 'running'):
                continue
            source = state.get('upscaled_preview')
            if isinstance(source, str) and Path(source).resolve() == path:
                raise DeleteRefused('in-use')
            command = state.get('command', [])
            if isinstance(command, list) and '--continue-from' in command:
                index = command.index('--continue-from') + 1
                if index < len(command) and isinstance(command[index], str) and Path(command[index]).resolve() == path:
                    raise DeleteRefused('continuation-in-use')
        # Content addressing needs the MP4 while it still exists. Optional
        # cleanup may fail, including in lightweight CI without PyAV.
        identifier = None
        try:
            from .continuation_store import video_id, delete_id
            identifier = video_id(path)
        except ModuleNotFoundError as error:
            if error.name not in ('av', __package__ + '.continuation_store'):
                raise
        except Exception as error:
            logging.warning('[FreeVideo] Continuation cleanup failed (%s).', type(error).__name__)
        trash = root / '.deleted'
        trash.mkdir(exist_ok=True)
        if not _plain(trash):
            raise DeleteRefused('not-freevideo')
        target = trash / ('%s-%d' % (identity.replace('/', '-'), time.time_ns()))
        try:
            folder.rename(target)
        except OSError as error:
            raise DeleteRefused('in-use') from error
        if identifier is not None:
            try:
                delete_id(identifier)
            except Exception as error:
                logging.warning('[FreeVideo] Continuation cleanup failed (%s).', type(error).__name__)
    freed, left = _remove(target)
    # A result-cache row naming this creation can no longer be reused.
    for index in (root / '.result-cache').glob('*.json'):
        try:
            if index.stat().st_size <= 1024 * 1024 and json.loads(index.read_text(encoding='utf-8')).get('id') == identity:
                index.unlink()
        except (OSError, ValueError, AttributeError):
            pass
    # Finish earlier deletions that Windows had kept open.
    for earlier in trash.iterdir():
        if earlier != target and _plain(earlier) and earlier.is_dir():
            freed += _remove(earlier)[0]
    return dict(id=identity, freed_bytes=freed, left=len(left))


def register():
    from aiohttp import web
    import folder_paths
    from server import PromptServer
    server = PromptServer.instance
    if server is None or getattr(server, '_freevideo_library', False):
        return
    server._freevideo_library = True
    thumbnails = asyncio.Semaphore(1)

    def release():
        try:
            result = release_earlier(folder_paths.get_output_directory())
            if result and result['freed_bytes']:
                logging.info('FreeVideo freed %.1f GB of decoded frames and audio from %d earlier videos.',
                             result['freed_bytes'] / 1e9, result['videos'])
        except Exception:
            logging.warning('FreeVideo could not free the decoded files of earlier videos.', exc_info=True)
    threading.Thread(target=release, name='freevideo-release-decoded', daemon=True).start()

    @server.routes.get('/freevideo/sampling-estimate')
    async def sampling_estimate(request):
        from .comfy_bridge import installation
        from .effort_forecast import estimate, local_records
        from .geometry import geometry
        try:
            canvas = geometry(int(request.query['width']), int(request.query['height']),
                              seconds=float(request.query['seconds']))
            from .two_pass import plan, sampling_canvas
            canvas = sampling_canvas(canvas)[0]
            task = request.query.get('task', 't2va')
            _, machine = installation()
            device = machine.get('device_identity') if machine.get('device_backend') == 'mps' else machine.get('gpu_uuid')
            rows = await asyncio.to_thread(local_records, folder_paths.get_output_directory(), device)
            adapters = request.query.get('adapters') == '1'
            # A small canvas runs in one pass whatever the switch says.
            result = {name: {str(steps): estimate(rows, canvas, base_steps=steps,
                                                 two_pass=plan(canvas, enabled, task, base_steps=steps)['enabled'],
                                                 task=task, adapters=adapters)
                              for steps in ((8,) if enabled else (8, 12, 16, 20))}
                      for name, enabled in (('single', False), ('two_pass', True))}
            return web.json_response(result, headers={'Cache-Control': 'no-store'})
        except (OSError, ValueError, TypeError, KeyError):
            # Estimation is advisory; installation and generation remain usable.
            return web.json_response({}, headers={'Cache-Control': 'no-store'})

    @server.routes.get('/freevideo/library')
    async def library(request):
        try:
            rows = await asyncio.to_thread(list_videos, folder_paths.get_output_directory(),
                                           before=request.query.get('before'),
                                           limit=int(request.query.get('limit', '24')))
            return web.json_response(rows, headers={'Cache-Control': 'no-store'})
        except ValueError as error:
            raise web.HTTPBadRequest(text=str(error)) from error

    @server.routes.get('/freevideo/library/thumbnail')
    async def preview(request):
        async with thumbnails:
            try:
                data = await asyncio.to_thread(thumbnail, folder_paths.get_output_directory(), request.query.get('id'))
            except Exception:
                # The full video remains playable if its thumbnail is missing.
                raise web.HTTPNotFound(text='Thumbnail unavailable') from None
        return web.Response(body=data, content_type='image/jpeg',
                            headers={'Cache-Control': 'private, max-age=86400'})

    @server.routes.post('/freevideo/library/delete')
    async def delete(request):
        try:
            body = await request.json()
            result = await asyncio.to_thread(delete_video, folder_paths.get_output_directory(),
                                             body.get('id') if isinstance(body, dict) else None,
                                             queue=getattr(server, 'prompt_queue', None))
        except DeleteRefused as error:
            return web.json_response(dict(deleted=False, reason=error.reason, kept=error.kept[:20]), status=409)
        except (OSError, ValueError, TypeError):
            raise web.HTTPNotFound(text='Saved video unavailable') from None
        return web.json_response(dict(result, deleted=True))

    @server.routes.get('/freevideo/library/download')
    async def download(request):
        try:
            path, name = await asyncio.to_thread(video_download, folder_paths.get_output_directory(), request.query.get('id'))
        except (OSError, ValueError, TypeError):
            raise web.HTTPNotFound(text='Saved video unavailable') from None
        return web.FileResponse(path, headers={'Content-Type': 'video/mp4',
            'Content-Disposition': 'attachment; filename="%s"' % name,
            'Cache-Control': 'private, no-store'})
