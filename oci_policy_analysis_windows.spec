# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['src/oci_policy_analysis/main.py'],
    pathex=[],
    binaries=[],
    datas=[('icons/*', 'icons')],
    hiddenimports=[
        'oci_policy_analysis.logic',
        'oci_policy_analysis.ui',
        'tkinter',
        'tkinter.ttk',
        'tkinter.filedialog',
        'tkinter.messagebox',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=False,     # ✅ include binaries
    name='oci-policy-analysis',
    debug=False,
    strip=False,
    upx=True,
    console=False,
    icon='icons/oci-policy-dg-viewer.ico',
    onefile=True,               # ✅ full embedded EXE
)
