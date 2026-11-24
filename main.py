import multiprocessing
import sys


def main():
    if '--self-test' in sys.argv:
        from utils.self_test import run
        report=None
        if '--self-test-report' in sys.argv:
            index=sys.argv.index('--self-test-report')
            if index+1>=len(sys.argv):raise SystemExit('--self-test-report needs a filename')
            report=sys.argv[index+1]
        raise SystemExit(run(report,require_libreoffice='--require-libreoffice' in sys.argv))
    if '--probe-workspace' in sys.argv:
        from utils.upgrade_probe import run as probe
        index=sys.argv.index('--probe-workspace')
        if index+1>=len(sys.argv):raise SystemExit('--probe-workspace needs a data directory')
        if '--probe-report' not in sys.argv:raise SystemExit('--probe-report needs a filename')
        report_index=sys.argv.index('--probe-report')
        if report_index+1>=len(sys.argv):raise SystemExit('--probe-report needs a filename')
        raise SystemExit(probe(sys.argv[index+1],sys.argv[report_index+1]))
    from PySide6.QtWidgets import QApplication
    from ui.main_window import MainWindow
    from utils.task_controller import shutdown_tasks
    from utils.qt_runtime import configure_qt_plugins
    configure_qt_plugins()
    from utils.engine_registry import EngineRegistry
    EngineRegistry.configure()
    app = QApplication(sys.argv)
    app.setOrganizationName("OfflineDocumentToolkit")
    app.setApplicationName("Offline Document Toolkit")
    from utils.version import VERSION
    app.setApplicationVersion(VERSION)

    window = MainWindow()
    app.aboutToQuit.connect(window.job_queue.shutdown)
    app.aboutToQuit.connect(shutdown_tasks)
    app.aboutToQuit.connect(lambda: window.workspace_store.release(window.job_queue.owner))
    window.show()
    incoming = [argument for argument in sys.argv[1:] if not argument.startswith('-')]
    if incoming:
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, lambda: window.workspace_page.add_files(incoming))

    sys.exit(app.exec())


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
