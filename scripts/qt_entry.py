"""Standalone Qt entry point for Nuitka; keeps package-relative imports intact."""

# Shared Nuitka project options are consumed by both the local builder and CI action.
# nuitka-project: --enable-plugin=pyside6
# nuitka-project: --user-package-configuration-file={MAIN_DIRECTORY}/qt.nuitka-package.config.yml
# nuitka-project: --include-qt-plugins=platforms,styles,imageformats,iconengines
# nuitka-project: --include-package-data=oci_policy_analysis
# nuitka-project: --include-distribution-metadata=oci-policy-analysis
# nuitka-project: --include-distribution-metadata=fastmcp
# nuitka-project: --include-distribution-metadata=mcp
# nuitka-project: --include-package=oci_policy_analysis.application.core.parser
# nuitka-project: --nofollow-import-to=oci_policy_analysis.presentation.desktop,oci_policy_analysis.main
# nuitka-project: --nofollow-import-to=pytest,IPython,notebook
# nuitka-project: --report=build/qt/nuitka-report.xml
# nuitka-project: --lto=no
# nuitka-project: --assume-yes-for-downloads
# nuitka-project-if: {OS} == "Darwin":
#    nuitka-project: --macos-app-name=OCI Policy Analysis Qt
#    nuitka-project: --macos-app-icon={MAIN_DIRECTORY}/../icons/oci-policy-dg-viewer.icns
# nuitka-project-if: {OS} == "Windows":
#    nuitka-project: --windows-console-mode=disable
#    nuitka-project: --windows-icon-from-ico={MAIN_DIRECTORY}/../icons/oci-policy-dg-viewer.ico

import logging
import sys

if __name__ == '__main__':
    if '--self-test' in sys.argv:
        logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
        from oci_policy_analysis.presentation.qt.frozen_smoke import main
    else:
        from oci_policy_analysis.presentation.qt.launcher import main
    raise SystemExit(main())
