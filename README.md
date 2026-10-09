# PocketLens

Use your iPhone as a Windows webcam over local Wi-Fi. PocketLens provides a
1280 × 720 DirectShow camera, WebRTC video, a JPEG fallback, and mirror controls.
Use your laptop or headset microphone.

## Requirements

- Windows 10/11 x64 and [64-bit Python 3.12](https://www.python.org/downloads/)
  with the Python launcher.
- iPhone with iOS 16 or later, Safari, and the same trusted Wi-Fi as your laptop.
- Internet access for the first dependency installation.

## Start

1. Extract the Windows release ZIP and double-click **Start PocketLens.cmd**.
2. On the dashboard, scan **Set up Safari access** and download the certificate
   profile from your laptop. Install it in **Settings → General → VPN & Device
   Management**, then enable trust in **General → About → Certificate Trust
   Settings**. Only install the profile from your own laptop.
3. Scan the pairing QR code and tap **Start camera** in Safari. Allow camera
   access and keep the phone unlocked, sideways, and connected to power.
4. Choose **PocketLens** in your meeting app. Restart the app if the camera is
   missing. If necessary, run **Install PocketLens System Camera.cmd** and
   approve Windows UAC.

The [dashboard](http://127.0.0.1:8766) shows the preview and stops the receiver.
**Mirror video** changes both the phone preview and outgoing webcam. Check what
another participant sees; meeting apps can also mirror their own preview.

| Problem | Fix |
| --- | --- |
| Startup fails | Run **Diagnose PocketLens.cmd**; check `%LOCALAPPDATA%\PocketLens\pocketlens-errors.log`. |
| Phone cannot connect | Run **Allow PocketLens Network.ps1** and approve UAC. Guest Wi-Fi or VPNs may isolate devices. |
| WebRTC cannot connect | Try **JPEG compatibility mode** on the phone page. |
| Camera missing | Restart the meeting app; try system installation or **Check browser webcam access** on the dashboard. |
| Capture freezes | Keep Safari visible. Tap Stop, then Start after an interruption. |
| Wrong laptop address | Stop the receiver and run `& '.\Start PocketLens.ps1' -Ip 192.168.1.20`, then scan the new QR code. |

PocketLens supports DirectShow consumers; Media Foundation-only apps may not
list it. Android, Windows ARM64, macOS, and Linux are unsupported. Phone locking,
backgrounding, or calls can interrupt capture. Test your meeting app before use.

## Privacy and removal

Video stays in memory and returns to a waiting screen after one second without
a frame. PocketLens does not record video or upload it to a cloud service.
The dashboard binds to localhost; setup and video use TCP 8764/8765 plus local
WebRTC UDP. Firewall rules allow only the local subnet. Do not port-forward
these ports or expose the receiver to the internet.

Runtime packages, settings, logs, and private certificate keys live under
`%LOCALAPPDATA%\PocketLens` (`POCKETLENS_DATA_DIR` overrides this). Never share
this directory or pairing codes. Updates retain the local CA and migrate the
old in-folder state. Keep an existing trusted phone certificate when upgrading;
its name may retain the previous app name. Rerun the network and system-camera
installers to update older installations.

To remove PocketLens, close camera clients and run **Remove PocketLens.cmd**,
then **Remove PocketLens Network Rules.cmd**. Remove the phone certificate
profile. You can then delete the app folder, `%LOCALAPPDATA%\PocketLens`, and
the unregistered files in `Program Files\PocketLens`.

## Development

From a source checkout, install Visual Studio 2022 Build Tools with **Desktop
development with C++** and a Windows SDK, then build both native libraries:

```powershell
& '.\Build PocketLens Native.ps1'
& '.\Start PocketLens.ps1'
```

Run the checks with Python 3.12, Node.js, and Chrome:

```powershell
py -3.12 -m venv work\venv
& .\work\venv\Scripts\python.exe -m pip install -r requirements-dev.txt
& .\work\venv\Scripts\python.exe -m ruff check .
& .\work\venv\Scripts\python.exe -m ruff format --check .
& .\work\venv\Scripts\python.exe -m unittest discover -s tests -v
node --test tests/phone-retry.test.js
& '.\Test PocketLens Browser.ps1'
```

Unit tests use temporary state and synthetic video. Browser integration opens
the real virtual webcam with a synthetic sender; stop phone capture and close
camera clients first. CI runs these checks and builds a Windows ZIP.

```powershell
& .\work\venv\Scripts\python.exe scripts/package_release.py --kind windows
& .\work\venv\Scripts\python.exe scripts/package_release.py --kind source
```

Archives and SHA-256 checksums are written to `dist/`. Private state, downloaded
toolchains, logs, and captures are excluded from Git and archives.

## License

[MIT](LICENSE). Native code derives from [tshino/softcam](https://github.com/tshino/softcam)
(commit `5113173d22a6aac4c9f30c36bb2cf900afef05f4`, copyright 2020 tshino;
[license](native/SOFTCAM-LICENSE.txt)) and Microsoft's
[DirectShow Base Classes](https://github.com/microsoft/Windows-classic-samples/tree/main/Samples/Win7Samples/multimedia/directshow/baseclasses)
([license](native/MICROSOFT-LICENSE.txt)). Upstream copyright notices are retained.
Python dependencies are installed separately and retain their own licenses.

## Author

Built by **Kyaw Myo Htet**.

LinkedIn: [Kyaw Myo Htet](https://www.linkedin.com/in/kyaw-myo-htet-a8840b377/)
