"""Load the existing application icon from package resources."""

from importlib.resources import files

from PySide6.QtGui import QIcon, QPixmap


def application_icon() -> QIcon:
    """Return the packaged application PNG as a Qt window/application icon.

    Returns:
        QIcon: Runtime icon; packaged executables also need their platform icon metadata.
    """
    data = files('oci_policy_analysis.assets.icons').joinpath('oci-policy-dg-viewer.png').read_bytes()
    pixmap = QPixmap()
    if not pixmap.loadFromData(data):
        raise RuntimeError('Application icon could not be decoded')
    return QIcon(pixmap)
