"""One image job at a time, with a leased worker retained until idle or video work."""
import atexit
import json
import math
from pathlib import Path
import queue
import secrets
import subprocess
import threading
import time
import uuid

from . import image_pack

BODY_LIMIT = 64 * 1024
CANCEL_GRACE = 5.
MAX_IMAGES = 4
ERRORS = {'no_memory', 'cancelled', 'generation_failed', 'invalid_request', 'busy'}


class Worker:
    """One reader owns each pipe; stderr is drained without retaining user text."""
    def __init__(self, process):
        self.process = process
        self.rows = queue.Queue()
        self.writer_mutex = threading.Lock()
        self.reader = threading.Thread(target=self.read, daemon=True)
        self.error_reader = threading.Thread(target=self.read_errors, daemon=True)
        self.reader.start()
        self.error_reader.start()

    def read(self):
        try:
            for line in self.process.stdout:
                if len(line) > 128 * 1024:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict):
                    self.rows.put(row)
        finally:
            self.rows.put(None)

    def read_errors(self):
        for _ in iter(lambda: self.process.stderr.read(1024), ''):
            pass

    def send(self, **row):
        with self.writer_mutex:
            self.process.stdin.write(json.dumps(row, ensure_ascii=True) + '\n')
            self.process.stdin.flush()

    def close(self):
        self.reader.join(timeout=5)
        self.error_reader.join(timeout=5)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            if not stream.closed:
                stream.close()


class Service:
    def __init__(self, installation, input_directory, *, video_busy=None, idle_seconds=180.):
        self.installation = installation
        self.input_directory = input_directory
        self.video_busy = video_busy or self._video_busy
        self.idle_seconds = idle_seconds
        self.mutex = threading.RLock()
        self.stop = threading.Event()
        self.session_stop = threading.Event()
        self.requests = queue.Queue()
        self.thread = None
        self.process = None
        self.worker = None
        self.key = None
        self.state = {}
        self._busy = False
        self.closed = False
        self.yielding = False
        atexit.register(self.close)

    @staticmethod
    def _video_busy():
        from ..resident_process import OWNER
        return OWNER.active

    def busy(self):
        return self._busy

    def info(self):
        _, machine = self.installation()
        spec = image_pack.catalog()
        return dict(ready=image_pack.ready(machine['model_root']), model=spec['repo'],
                    bytes=sum(row['bytes'] for row in spec['groups']['image']), busy=self.busy(),
                    max_images=MAX_IMAGES)

    def request(self, value):
        if not isinstance(value, dict):
            raise ValueError('invalid_request')
        prompt = value.get('prompt')
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 2000:
            raise ValueError('invalid_prompt')
        dimensions = [value.get(name) for name in ('width', 'height')]
        if any(type(size) is not int or not 256 <= size <= 2048 for size in dimensions):
            raise ValueError('invalid_dimensions')
        seed = value.get('seed')
        if seed is not None and (type(seed) is not int or not -2**63 <= seed < 2**64):
            raise ValueError('invalid_seed')
        images = value.get('images', [])
        if not isinstance(images, list):
            raise ValueError('invalid_media')
        if len(images) > MAX_IMAGES:
            raise ValueError('too_many_images')
        directory = Path(self.input_directory()).resolve()
        paths = []
        for name in images:
            # A file in the input directory, or one of our own results as freevideo-image/<name>.
            folder, _, leaf = name.rpartition('/') if isinstance(name, str) else ('', '', '')
            if (not isinstance(name, str) or not leaf or leaf in ('.', '..')
                    or folder not in ('', 'freevideo-image')
                    or any(char in name for char in ('\\', ':', '\0'))):
                raise ValueError('invalid_media')
            parent = directory / folder if folder else directory
            path = parent / leaf
            if (parent.is_symlink() or path.is_symlink() or parent.resolve() != parent
                    or path.resolve().parent != parent or not path.is_file()):
                raise ValueError('invalid_media')
            paths.append(str(path))
        output = directory / 'freevideo-image'
        if output.is_symlink() or output.resolve().parent != directory:
            raise ValueError('invalid_media')
        output.mkdir(exist_ok=True)
        return dict(prompt=prompt, width=dimensions[0] // 32 * 32, height=dimensions[1] // 32 * 32,
                    seed=seed, images=paths, path=str(output / (uuid.uuid4().hex + '.png')))

    def start(self, action, value, *, checkpoint_directory=None):
        if action not in ('generate', 'compose'):
            raise ValueError('invalid_request')
        with self.mutex:
            if self.closed:
                raise ValueError('closed')
            if self.yielding or self.video_busy():
                raise ValueError('busy_video')
            if self.busy() or self.thread is not None and self.thread.is_alive() and self.session_stop.is_set():
                raise ValueError('busy')
            root, machine = self.installation()
            if not image_pack.ready(machine['model_root']):
                raise ValueError('pack_missing')
            if action == 'compose':
                from . import compose
                value = compose.build(value, self.input_directory())
            value = self.request(value)
            if checkpoint_directory is not None:value['checkpoint_directory']=str(checkpoint_directory)
            self.preflight(machine, value)
            self.key = secrets.token_urlsafe(24)
            self.stop.clear()
            self.state = dict(phase='starting')
            self._busy = True
            if self.thread is None or not self.thread.is_alive():
                self.session_stop = threading.Event()
                self.requests = queue.Queue()
                self.thread = threading.Thread(target=self.work, args=(root, machine),
                                               name='freevideo-image-gen', daemon=True)
                self.requests.put(value)
                self.thread.start()
            else:
                self.requests.put(value)
            return dict(job=self.key)

    def memory_budget(self, machine):
        """Bound the driver query, without importing Torch or starting a worker."""
        if machine.get('device_backend', 'cuda') != 'cuda':
            return None
        from ..background_room import Gpu, family
        from ..background_compile import COMPILE
        from ..gpu_budget import open_bounded
        from ..resident_process import OWNER

        def read():
            gpu = Gpu(machine.get('gpu_uuid'))
            try:
                memory = gpu.memory()
                if memory is None:
                    return None
                used, total = memory
                if not total or not 0 <= used <= total:
                    return None
                # work() releases idle video/compile models; the image worker
                # reuses its own allocator. Never credit an unrelated process.
                owned = set()
                for process in (self.process, None if OWNER.active else OWNER.process, COMPILE.process):
                    if process is not None and process.poll() is None:
                        owned.update(family(process.pid))
                rows = gpu.processes() if owned else {}
                if owned and (rows is None or not owned.intersection(rows)
                              or any(rows.get(pid) is None for pid in owned if pid in rows)):
                    # An unreported owned pool must not cause a false refusal.
                    # The worker still checks live capacity before inference.
                    return total
                credit = sum(size for pid, size in rows.items() if pid in owned)
                return min(total, total - used + credit)
            finally:
                gpu.close()

        try:
            return open_bounded(read, .5)
        except (OSError, RuntimeError, AttributeError, ValueError):
            return None

    def preflight(self, machine, value):
        budget = self.memory_budget(machine)
        if budget is None:
            return
        from PIL import Image
        from .image_policy import plan_image
        reference_pixels = 0
        for path in value['images']:
            with Image.open(path) as image:
                scale = (1024**2 / (image.width * image.height)) ** .5
                reference_pixels += round(image.width * scale) * round(image.height * scale)
        plan = plan_image(gpu_budget_bytes=budget, width=value['width'], height=value['height'],
                          reference_pixels=reference_pixels)
        if not plan.feasible:
            raise ValueError('no_memory')

    def status(self, key):
        with self.mutex:
            if (not isinstance(key, str) or not self.key
                    or not secrets.compare_digest(key.encode('utf-8'), self.key.encode('utf-8'))):
                raise ValueError('unknown_job')
            return dict(self.state)

    def cancel(self, key):
        with self.mutex:
            row = self.status(key)
            if not self.busy():
                return row
            self.stop.set()
            self.state['phase'] = 'cancelling'
            return dict(phase='cancelling')

    def stop_for_generation(self, only_idle=False):
        """Reap even an in-flight spawn before video acquires the runtime lease.

        ``only_idle`` is for other users of the lease (the prompt model): they get it
        back from an idle worker but never cut off an image that is being made.
        """
        with self.mutex:
            if only_idle and (self._busy or self.thread is None or not self.thread.is_alive()):
                return False
            self.yielding = True
            self.stop.set()
            self.session_stop.set()
            thread = self.thread
        try:
            if thread is not None and thread is not threading.current_thread():
                thread.join()
        finally:
            with self.mutex:
                self.yielding = False
        return True

    def close(self):
        with self.mutex:
            self.closed = True
        self.stop_for_generation()

    def environment(self, root):
        from ..comfy_bridge import source_root
        from ..comfy_environment import isolated_environment
        from .. import processes, resident_process
        env = isolated_environment(root, source_root())
        for name in ('FREEVIDEO_RUNTIME_LOCK_FD', processes.HANDLE_ENV, resident_process.ENV,
                     'FREEVIDEO_PROMPT_PRESTART_WORKER'):
            env.pop(name, None)
        return env

    def spawn(self, root, machine, env, descriptor):
        from .. import processes
        command = processes.module_command('freevideo_engine.image_gen.worker', image_pack.base(machine['model_root']),
                                           '--device', machine.get('device_backend', 'cuda'),
                                           '--idle-seconds', self.idle_seconds)
        command[0] = machine['comfy_python']
        env = dict(env, FREEVIDEO_RUNTIME_LOCK_FD=str(descriptor))
        return processes.popen(command, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace',
                               pass_fds=(descriptor,), supervise=True, start_new_session=True)

    def work(self, root, machine):
        from ..locking import runtime_lock
        from .. import processes, resident_process
        session = None
        failure = 'worker_exit'
        try:
            from ..background_compile import COMPILE
            from ..encoder_prewarm import IDLE
            COMPILE.stop()
            if self.video_busy() or resident_process.OWNER.active:
                raise BlockingIOError('busy_video')
            resident_process.OWNER.stop_prewarm()
            IDLE.stop()
            with runtime_lock(Path(root) / 'engine.lock', inherit=False) as descriptor:
                try:
                    if self.session_stop.is_set():
                        return
                    env = self.environment(root)
                    owner = resident_process.OWNER
                    if owner.process is not None and owner.process.poll() is None and owner.endpoint:
                        env[resident_process.ENV] = str(owner.endpoint)
                        try:
                            resident_process.release_idle_cache(env, descriptor)
                            resident_process.OWNER.record(action='released', reason='image_model')
                        except resident_process.SessionRestarted:
                            pass
                        env.pop(resident_process.ENV, None)
                    if self.session_stop.is_set():
                        return
                    if self.video_busy():
                        raise BlockingIOError('busy_video')
                    session = Worker(self.spawn(root, machine, env, descriptor))
                    with self.mutex:
                        self.worker = session
                        self.process = session.process
                    while not self.session_stop.is_set():
                        try:
                            value = self.requests.get(timeout=.05)
                        except queue.Empty:
                            with self.mutex:
                                if session.process.poll() is not None and self.requests.empty():
                                    self.session_stop.set()
                                    break
                            continue
                        if session.process.poll() == 0:
                            session.process.wait()
                            session.close()
                            session = Worker(self.spawn(root, machine, env, descriptor))
                            with self.mutex:
                                self.worker = session
                                self.process = session.process
                        self.infer(session, value)
                finally:
                    # Keep the parent's lease until the whole owned process tree exits.
                    if session is not None:
                        try:
                            if session.process.poll() is None:
                                session.send(action='close')
                                session.process.wait(timeout=5)
                        except (OSError, subprocess.TimeoutExpired):
                            pass
                        processes.stop(session.process, grace=5)
                        session.process.wait()
                        session.close()
        except BlockingIOError:
            failure = 'busy_video'
        except Exception:
            failure = 'worker_exit'
        finally:
            with self.mutex:
                self.process = self.worker = None
                self.session_stop.set()
                if self.busy():
                    self.state = (dict(phase='cancelled') if self.stop.is_set()
                                  else dict(phase='failed', error=failure))
                    self._busy = False

    def infer(self, session, value):
        session.send(action='generate', **value)
        cancelled_at = None
        deadline = time.monotonic() + 600
        while True:
            if self.stop.is_set() and cancelled_at is None:
                session.send(action='cancel')
                cancelled_at = time.monotonic()
            if cancelled_at is not None and time.monotonic() - cancelled_at > CANCEL_GRACE:
                raise TimeoutError('cancelled')
            if self.session_stop.is_set():
                return
            if time.monotonic() > deadline:
                raise TimeoutError('worker_exit')
            try:
                row = session.rows.get(timeout=.05)
            except queue.Empty:
                continue
            if row is None:
                raise RuntimeError('worker_exit')
            phase = row.get('phase')
            if phase == 'progress':
                stage, fraction = row.get('stage'), row.get('fraction')
                if (stage in ('load', 'text', 'encode', 'denoise', 'decode') and type(fraction) in (int, float)
                        and math.isfinite(fraction) and 0 <= fraction <= 1):
                    with self.mutex:
                        self.state.update(phase='cancelling' if self.stop.is_set() else 'progress',
                                          stage=stage, fraction=fraction)
            elif phase == 'paused':
                self.session_stop.set()
                with self.mutex:self.state=dict(phase='paused');self._busy=False
                return
            elif phase in ('result', 'error'):
                if self.stop.is_set() or row.get('code') == 'cancelled':
                    result = dict(phase='cancelled')
                elif phase == 'error':
                    code = row.get('code')
                    result = dict(phase='failed', error=code if code in ERRORS else 'generation_failed')
                    if code == 'no_memory':
                        result['message_zh'] = '内存或显存不足，请降低图像尺寸或减少参考图。'
                else:
                    path = Path(value['path'])
                    if row.get('path') != str(path) or path.is_symlink() or not path.is_file():
                        raise RuntimeError('worker_exit')
                    from PIL import Image
                    with Image.open(path) as image:
                        if image.format != 'PNG' or image.size != (value['width'], value['height']):
                            raise RuntimeError('worker_exit')
                        image.verify()
                    seconds = row.get('seconds')
                    if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0:
                        raise RuntimeError('worker_exit')
                    result = dict(phase='complete', file='freevideo-image/' + path.name,
                                  seconds=seconds, plan=row.get('plan'))
                with self.mutex:
                    self.state = result
                    self._busy = False
                return


def stop_prestart_for_generation(server):
    service = getattr(server, '_freevideo_image_gen', None)
    if service is not None:
        service.stop_for_generation()


def get_service(server=None):
    """The image service of this server, for callers in the same process (the Agent).

    They call ``start('generate', {...})``, ``status(job)``, ``cancel(job)`` and
    ``info()`` directly with the same arguments, results and error codes as the
    HTTP routes; only the page token is not needed. None before ``register()``.
    """
    if server is None:
        from server import PromptServer
        server = PromptServer.instance
    return getattr(server, '_freevideo_image_gen', None)


def release_idle_worker(server):
    """Hand engine.lock back from a worker that is only waiting for its idle exit."""
    service = getattr(server, '_freevideo_image_gen', None)
    if service is not None:
        service.stop_for_generation(only_idle=True)


def register():
    from aiohttp import web
    from server import PromptServer
    import folder_paths
    from ..comfy_bridge import installation
    server = PromptServer.instance
    if server is None or getattr(server, '_freevideo_image_gen', None) is not None:
        return

    def video_busy():
        running, pending = server.prompt_queue.get_current_queue()
        return bool(running or pending) or Service._video_busy()

    service = Service(installation, folder_paths.get_input_directory, video_busy=video_busy)
    server._freevideo_image_gen = service
    token = secrets.token_urlsafe(24)

    @server.routes.get('/freevideo/image-gen')
    async def info(request):
        try:
            return web.json_response(dict(service.info(), token=token))
        except (OSError, ValueError):
            return web.json_response(dict(error='setup_required'), status=400)

    @server.routes.post('/freevideo/image-gen/{action}')
    async def action(request):
        header = request.headers.get('X-FreeVideo-Image', '')
        if not secrets.compare_digest(header.encode('utf-8'), token.encode('utf-8')):
            return web.json_response(dict(error='reload'), status=403)
        try:
            if request.content_length and request.content_length > BODY_LIMIT:
                raise ValueError('invalid_request')
            body = bytearray()
            while True:
                chunk = await request.content.read(min(8192, BODY_LIMIT + 1 - len(body)))
                if not chunk:
                    break
                body.extend(chunk)
                if len(body) > BODY_LIMIT:
                    raise ValueError('invalid_request')
            value = json.loads(body)
            if not isinstance(value, dict):
                raise ValueError('invalid_request')
            name = request.match_info['action']
            if name == 'status':
                result = service.status(value.get('job'))
            elif name == 'cancel':
                result = service.cancel(value.get('job'))
            else:
                result = service.start(name, value)
            return web.json_response(result)
        except (ValueError, OSError) as error:
            codes = {'invalid_request', 'invalid_prompt', 'invalid_dimensions', 'invalid_seed', 'invalid_media',
                     'too_many_images', 'busy', 'busy_video', 'no_memory', 'pack_missing', 'unknown_job', 'closed'}
            return web.json_response(dict(error=str(error) if str(error) in codes else 'invalid_request'), status=400)
