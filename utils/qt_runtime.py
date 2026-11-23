"""Discover the installed Qt plugins without binding the app to a machine."""
import os
from pathlib import Path


def configure_qt_plugins():
    from PySide6.QtCore import QCoreApplication, QLibraryInfo
    plugins = QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath)
    QCoreApplication.addLibraryPath(plugins)
    # Some existing environments also contain the GUI build of OpenCV, which
    # injects its incompatible Qt plugins while importing cv2. New installations
    # use headless OpenCV; repair that specific collision for existing users.
    for name, replacement in (("QT_PLUGIN_PATH", plugins),
                              ("QT_QPA_PLATFORM_PLUGIN_PATH", str(Path(plugins) / "platforms"))):
        if not os.environ.get(name) or "cv2" in os.environ.get(name, ""):
            os.environ[name] = replacement
