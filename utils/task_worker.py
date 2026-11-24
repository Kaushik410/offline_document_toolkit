"""Run document engines in isolated, cancellable processes (including MuPDF)."""
import inspect
import multiprocessing as mp
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import threading
import time

from PySide6.QtCore import QObject, Signal, QRunnable, Slot


def _execute(connection, task_fn, args, kwargs, scratch):
    if os.name == 'posix':
        os.setsid()
    # If the GUI crashes, stop this entire job rather than leave an orphan
    # writing checkpoints while a restarted queue claims the same job.
    parent = mp.parent_process()
    if parent is not None:
        def watch_parent():
            while parent.is_alive():
                time.sleep(0.25)
            if os.name == 'posix':
                os.killpg(os.getpid(), signal.SIGKILL)
            elif os.name == 'nt':
                subprocess.run(['taskkill','/PID',str(os.getpid()),'/T','/F'],capture_output=True,timeout=10)
            os._exit(1)
        threading.Thread(target=watch_parent,daemon=True).start()
    tempfile.tempdir = scratch
    os.environ['TMPDIR'] = scratch
    from utils import output_utils
    output_utils._report_temp = lambda path: connection.send(('temporary', path))
    connection.send(('started', None))
    try:
        from utils.engine_registry import EngineRegistry
        EngineRegistry.configure()
        parameters = inspect.signature(task_fn).parameters
        callbacks = {
            'progress_callback': lambda n: connection.send(('progress', n)),
            'status_callback': lambda s: connection.send(('status', s)),
        }
        kwargs = dict(kwargs)
        kwargs.update({k: v for k, v in callbacks.items() if k in parameters})
        result = task_fn(*args, **kwargs)
        connection.send(('finished', result))
    except Exception as error:
        connection.send(('error', f'{type(error).__name__}: {error}'))
    finally:
        connection.close()


class WorkerSignals(QObject):
    finished = Signal(object)
    error = Signal(str)
    cancelled = Signal()
    progress = Signal(int)
    status = Signal(str)


class TaskWorker(QRunnable):
    def __init__(self, task_fn, *args, **kwargs):
        super().__init__()
        self.task_fn, self.args, self.kwargs = task_fn, args, kwargs
        self.signals = WorkerSignals()
        self._cancelled = threading.Event()

    def cancel(self):
        self._cancelled.set()

    def is_cancelled(self):
        return self._cancelled.is_set()

    @staticmethod
    def _stop(process, group_started):
        if not process.is_alive():
            return
        if os.name == 'posix' and group_started:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        elif os.name == 'nt':
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                           capture_output=True, timeout=10)
        else:
            process.terminate()
        process.join(timeout=1)
        if os.name == 'posix' and group_started:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if process.is_alive():
            process.kill()
        process.join(timeout=2)

    @Slot()
    def run(self):
        ctx = mp.get_context('spawn')
        receiver, sender = ctx.Pipe(duplex=False)
        temporary_outputs = set()
        outcome = None
        group_started = False
        pipe_closed = False
        process = None

        def receive():
            nonlocal outcome, group_started
            kind, value = receiver.recv()
            if kind == 'temporary':
                temporary_outputs.add(value)
            elif kind == 'started':
                group_started = True
            elif kind in ('finished', 'error'):
                outcome = kind, value
            elif kind == 'progress':
                self.signals.progress.emit(value)
            elif kind == 'status':
                self.signals.status.emit(value)

        def receive_available(timeout=0):
            nonlocal pipe_closed
            try:
                if not receiver.poll(timeout):
                    return False
                receive()
                return True
            except EOFError:
                pipe_closed = True
            except OSError as error:
                # Windows named pipes report peer closure from poll()/recv()
                # as ERROR_BROKEN_PIPE or ERROR_NO_DATA, including after a
                # complete result has already arrived.
                if getattr(error,'winerror',None) not in (109,232):
                    raise
                pipe_closed = True
            return False

        try:
            with tempfile.TemporaryDirectory(prefix='odt-task-') as scratch:
                if not self.is_cancelled():
                    process = ctx.Process(target=_execute, args=(
                        sender, self.task_fn, self.args, self.kwargs, scratch))
                    process.start()
                    sender.close()
                    while process.is_alive():
                        receive_available(0.05)
                        if pipe_closed:
                            break
                        if self.is_cancelled():
                            self._stop(process, group_started)
                            break
                    process.join(timeout=2)
                    while not pipe_closed and receive_available():
                        pass
                    if process.is_alive():
                        self._stop(process, group_started)
                    elif os.name == 'posix' and group_started:
                        # A timed-out CLI launcher can exit before its engine.
                        # Its session belongs exclusively to this job.
                        try:
                            os.killpg(process.pid, signal.SIGTERM)
                        except ProcessLookupError:
                            pass
                for path in temporary_outputs:
                    Path(path).unlink(missing_ok=True)
            if self.is_cancelled():
                self.signals.cancelled.emit()
            elif outcome:
                getattr(self.signals, outcome[0]).emit(outcome[1])
            else:
                self.signals.error.emit('The document worker exited unexpectedly.')
        except Exception as error:
            if process and process.pid:
                self._stop(process, group_started)
            for path in temporary_outputs:
                Path(path).unlink(missing_ok=True)
            self.signals.error.emit(str(error))
        finally:
            sender.close()
            receiver.close()
