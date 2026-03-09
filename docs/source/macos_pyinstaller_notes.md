# macOS & PyInstaller: Additional Notes for Tkinter Context Menus

Some caveats and workarounds if right-click/context menus in your Tkinter-based app do not work after building a standalone executable:

## 1. Universal Event Binding (Already addressed)
- Bind both `'<Button-3>'` and `'<Control-Button-1>'` events to your right-click handler.
- Ensures right-click and Control+Click both invoke the menu, covering all major platforms (see `policy_browser_tab.py`).

## 2. App Sandboxing & Security
- macOS Gatekeeper may restrict event propagation for non-codesigned apps.
- If the app was downloaded, quarantined, or is not properly codesigned/notarized, some events (especially mouse or keyboard shortcuts) may be dropped or ignored.
- Symptom: context menu/functionality only works when "run from terminal," but fails double-clicking the bundle/app, or after "moving to Applications."

## 3. Codesigning & Notarization
- For a seamless user experience, especially if distributing outside your own machine, sign and notarize the app bundle.
- Use `codesign` with a real Developer ID (not ad hoc) and notarize with Apple if possible:
    ```sh
    codesign --deep --force --options runtime --sign "Developer ID Application: Your Name" dist/YourApp.app
    ```
- For local development, you can remove the quarantine attribute after unpacking/copying:
    ```sh
    xattr -dr com.apple.quarantine dist/YourApp.app
    ```

## 4. Accessibility (Events Permission)
- If your app handles input events or controls other apps, it might need "Accessibility" permissions under **System Preferences > Security & Privacy > Privacy > Accessibility**.
- Add your app to the allowed list if context menus, drag-and-drop, or other UI events are missing or unreliable.

## 5. Additional Known Issues
- Tkinter’s mouse event support is reliable when running from source, but sometimes incomplete for frozen apps due to the differences in event loop integration.
- Always test both native and frozen app on all target OS versions.

## Troubleshooting Steps
- If right-click/context menus work from command line but not as an .app:
    - Confirm the cross-platform binding in code.
    - Remove quarantine: `xattr -dr com.apple.quarantine dist/YourApp.app`
    - Try codesigning (even ad hoc, for local dev): `codesign --deep -fs - dist/YourApp.app`
    - If still broken, check for crash logs in Console.app (macOS), or run app from terminal to read stderr/stdout messages.