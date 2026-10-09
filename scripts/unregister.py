"""Remove only this camera's current-user registry entries, using the standard library."""

import winreg

CLSID = "{E54B414E-D1EC-4D35-B8C4-AD9D9E0F2163}"
CATEGORY = "{860BB310-5D01-11D0-BD3B-00A0C911CE86}"

for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
    for path in (
        f"Software\\Classes\\CLSID\\{CLSID}\\InprocServer32",
        f"Software\\Classes\\CLSID\\{CLSID}",
        f"Software\\Classes\\CLSID\\{CATEGORY}\\Instance\\{CLSID}",
    ):
        try:
            winreg.DeleteKeyEx(winreg.HKEY_CURRENT_USER, path, view, 0)
        except FileNotFoundError:
            pass
print("Camera removed from this Windows account.")
