"""Persistent ImageRunner owner; stdin/stdout contain one JSON object per line."""
import argparse
from contextlib import ExitStack, redirect_stdout
import json
import os
from pathlib import Path
import queue
import sys
import threading
import time


class Inbox:
    """Read cancellation while the main thread is inside a denoising step."""
    def __init__(self, stream, send):
        self.stream = stream
        self.send = send
        self.rows = queue.Queue()
        self.cancel = threading.Event()
        self.closed = threading.Event()
        self.mutex = threading.Lock()
        self.busy = False
        self.reader = threading.Thread(target=self.read, daemon=True)
        self.reader.start()

    def read(self):
        try:
            while not self.closed.is_set():
                line = self.stream.readline(64 * 1024 + 1)
                if not line:
                    break
                try:
                    if len(line.encode('utf-8')) > 64 * 1024:
                        raise ValueError('invalid_request')
                    value = json.loads(line)
                    if not isinstance(value, dict):
                        raise ValueError('invalid_request')
                    action = value.get('action')
                    with self.mutex:
                        if action == 'cancel':
                            if self.busy:
                                self.cancel.set()
                        elif action == 'close':
                            break
                        elif action == 'generate':
                            if self.busy:
                                self.send(phase='error', code='busy')
                            else:
                                self.busy = True
                                self.cancel.clear()
                                self.rows.put(value)
                        else:
                            raise ValueError('invalid_request')
                except (ValueError, UnicodeError):
                    self.send(phase='error', code='invalid_request')
        finally:
            self.closed.set()
            self.cancel.set()
            self.rows.put(None)


def _flatten(image):
    """RGB copy; transparency is shown on white, as the encoder's vision tower sees it."""
    from PIL import Image
    if image.mode in ('RGBA', 'LA') or 'transparency' in image.info:
        rgba = image.convert('RGBA')
        base = Image.new('RGBA', rgba.size, (255, 255, 255, 255))
        return Image.alpha_composite(base, rgba).convert('RGB')
    return image.convert('RGB')


def load_runner(pack_dir, device, *, progress=None):
    # Importing this module in ComfyUI or in CPU protocol tests never loads torch.
    from .image_runner import ImageRunner
    return ImageRunner(pack_dir, device=device, progress=progress)


def serve(pack_dir, *, device='cuda', idle_seconds=180., stream=None, output=None, factory=None):
    stream = sys.stdin if stream is None else stream
    output = sys.stdout if output is None else output
    factory = factory or load_runner
    output_mutex = threading.Lock()

    def send(**row):
        with output_mutex:
            output.write(json.dumps(row, ensure_ascii=True, allow_nan=False) + '\n')
            output.flush()

    inbox = Inbox(stream, send)
    runner = None
    try:
        while not inbox.closed.is_set():
            try:
                value = inbox.rows.get(timeout=idle_seconds)
            except queue.Empty:
                break
            if value is None or inbox.closed.is_set():
                break
            started = time.monotonic()
            result = None
            try:
                from PIL import Image
                with ExitStack() as stack, redirect_stdout(sys.stderr):
                    if inbox.cancel.is_set():
                        raise InterruptedError('cancelled')
                    progress = lambda stage, fraction: send(phase='progress', stage=stage, fraction=fraction)
                    if runner is None:
                        runner = factory(pack_dir, device, progress=progress)
                    references = []
                    for path in value.get('images', []):
                        image = stack.enter_context(Image.open(path))
                        references.append(_flatten(image))
                    image = runner.generate(
                        value['prompt'], width=value['width'], height=value['height'],
                        seed=value.get('seed'), reference_images=references,
                        progress=progress,
                        cancel=inbox.cancel.is_set,**({'checkpoint_directory':value['checkpoint_directory']} if value.get('checkpoint_directory') else {}))
                    if inbox.cancel.is_set():
                        raise InterruptedError('cancelled')
                    # The parent chooses a fresh path under ComfyUI input.
                    # Exclusive creation never replaces an existing user file.
                    with Path(value['path']).open('xb') as target:
                        image.save(target, format='PNG')
                    plan = runner.stats().get('plan')
                result = dict(phase='result', path=value['path'], seconds=time.monotonic() - started, plan=plan)
            except SystemExit as error:
                if error.code!=77:raise
                result=dict(phase='paused');inbox.closed.set()
            except MemoryError:
                result = dict(phase='error', code='no_memory', message_zh='内存或显存不足，请降低图像尺寸或减少参考图。')
            except Exception as error:
                # Exceptions may echo prompts, filenames or model paths.
                code = ('cancelled' if inbox.cancel.is_set() else
                        'no_memory' if type(error).__name__ == 'OutOfMemoryError' else 'generation_failed')
                result = dict(phase='error', code=code)
            finally:
                with inbox.mutex:
                    inbox.busy = False
                    if result is not None:
                        send(**result)
    finally:
        inbox.closed.set()
        inbox.cancel.set()
        if runner is not None:
            with redirect_stdout(sys.stderr):
                runner.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pack_dir', type=Path)
    parser.add_argument('--device', default='cuda')
    parser.add_argument('--idle-seconds', type=float, default=180.)
    args = parser.parse_args()
    if not 0 < args.idle_seconds < float('inf'):
        parser.error('--idle-seconds must be positive and finite')
    stream = None
    if os.name == 'nt':
        from ..win32 import private_stdin
        try:
            stream = private_stdin()
        except OSError as error:
            print('private stdin unavailable, reading stdin directly: %s' % error, file=sys.stderr, flush=True)
    serve(args.pack_dir, device=args.device, idle_seconds=args.idle_seconds, stream=stream)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
