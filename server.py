"""Private LAN camera receiver. Video remains in memory; no external services."""

import argparse
import asyncio
import datetime as dt
import io
import ipaddress
import json
import os
from pathlib import Path
import plistlib
import secrets
import shutil
import signal
import socket
import ssl
import uuid
import webbrowser
from aiohttp import web, WSMsgType
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
import cv2
import qrcode
from camera import Camera, register, BASE, NAME
from rtc_receiver import Receiver


def data_directory():
    """Runtime state lives outside the app folder so ZIP updates keep the pairing CA."""
    override = os.environ.get("POCKETLENS_DATA_DIR")
    if override:
        return Path(override).resolve()
    root = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    return Path(root) / "PocketLens" if root else Path.home() / ".pocketlens"


def state_directory(data):
    """Return the state path, migrating any legacy in-folder state once."""
    directory = data / "state"
    legacy = BASE / "work" / "interview-camera-state"
    if not directory.exists() and legacy.is_dir():
        directory.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(legacy, directory)
    return directory


STATE = data_directory() / "state"


def lan_ip():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            # UDP connect chooses an interface; it sends no packet.
            s.connect(("192.168.1.1", 9))
            return s.getsockname()[0]
        except OSError:
            return socket.gethostbyname(socket.gethostname())


def certificates(ip):
    STATE.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc)
    if not (STATE / "root-key.pem").exists():
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "PocketLens Local CA")])
        cert = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(minutes=5))
            .not_valid_after(now + dt.timedelta(days=365))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(
                x509.KeyUsage(False, False, False, False, False, True, True, False, False),
                critical=True,
            )
            .sign(key, hashes.SHA256())
        )
        (STATE / "root-key.pem").write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        (STATE / "root.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    root = x509.load_pem_x509_certificate((STATE / "root.pem").read_bytes())
    key = serialization.load_pem_private_key((STATE / "root-key.pem").read_bytes(), password=None)
    if root.not_valid_after_utc <= now:
        raise RuntimeError(
            "Local CA expired; remove its iPhone profile and regenerate the state directory."
        )
    leafkey = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "PocketLens")])
    leaf = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(root.subject)
        .public_key(leafkey.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(min(root.not_valid_after_utc, now + dt.timedelta(days=90)))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.IPAddress(ipaddress.ip_address(ip)),
                    x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                    x509.DNSName("localhost"),
                ]
            ),
            critical=False,
        )
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(key, hashes.SHA256())
    )
    (STATE / "server.pem").write_bytes(
        leaf.public_bytes(serialization.Encoding.PEM)
        + root.public_bytes(serialization.Encoding.PEM)
    )
    (STATE / "server-key.pem").write_bytes(
        leafkey.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    profile = {
        "PayloadContent": [
            {
                "PayloadType": "com.apple.security.root",
                "PayloadVersion": 1,
                "PayloadIdentifier": "local.pocketlens.ca",
                "PayloadUUID": str(uuid.uuid4()),
                "PayloadDisplayName": "PocketLens Local CA",
                "PayloadContent": root.public_bytes(serialization.Encoding.DER),
            }
        ],
        "PayloadType": "Configuration",
        "PayloadVersion": 1,
        "PayloadIdentifier": "local.pocketlens",
        "PayloadUUID": str(uuid.uuid4()),
        "PayloadDisplayName": "PocketLens — local HTTPS",
        "PayloadDescription": "Trusts the certificate created on your laptop for the local camera page. Contains no device management, VPN, or account settings.",
        "PayloadRemovalDisallowed": False,
    }
    return plistlib.dumps(profile), root.fingerprint(hashes.SHA256()).hex()


@web.middleware
async def headers(request, handler):
    try:
        response = await handler(request)
    except web.HTTPException as error:
        response = error
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = "camera=(self), microphone=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; "
        "object-src 'none'; base-uri 'self'; form-action 'none'; frame-ancestors 'none'"
    )
    if isinstance(response, web.HTTPException):
        raise response
    return response


def file_handler(name):
    async def serve(request):
        return web.FileResponse(BASE / "web" / name)

    return serve


def create_apps(camera, ip, profile, fingerprint, token, stop):
    """Create the three HTTP surfaces without registering a Windows device."""
    phone_url = f"https://{ip}:8765/#{token}"
    setup_url = f"http://{ip}:8764/"
    producer = None

    def apply_flip(flip):
        if type(flip) is not bool:
            raise ValueError("flip must be boolean")
        temporary = STATE / "settings.tmp"
        temporary.write_text(json.dumps({"flip": flip}))
        temporary.replace(STATE / "settings.json")
        with camera.lock:
            camera.flip = flip

    async def send_settings(ws):
        if ws is not None and ws.prepared and not ws.closed:
            try:
                await ws.send_json({"type": "settings", "flip": camera.flip})
            except ConnectionError:
                pass

    def check_pairing(request):
        if not secrets.compare_digest(request.query.get("token", "").encode(), token.encode()):
            raise web.HTTPForbidden(text="Scan the pairing code on your laptop again.")
        if request.headers.get("Origin") not in (
            f"https://{ip}:8765",
            "https://127.0.0.1:8765",
            "https://localhost:8765",
        ):
            raise web.HTTPForbidden(text="Unexpected origin")

    async def token_check(request):
        # Same-origin browser fetches omit Origin, so the secret token is the only gate.
        if not secrets.compare_digest(request.query.get("token", "").encode(), token.encode()):
            raise web.HTTPForbidden(text="Scan the pairing code on your laptop again.")
        return web.Response(status=204)

    async def stream(request):
        nonlocal producer
        check_pairing(request)
        if producer is not None and not producer.closed:
            raise web.HTTPConflict(
                text="Another phone is connected. Stop it before pairing another."
            )
        ws = web.WebSocketResponse(max_msg_size=1024 * 1024, heartbeat=10, compress=False)
        # Reserve before the upgrade await, so simultaneous connections cannot race.
        producer = ws
        rtc = None
        try:
            await ws.prepare(request)
            async for msg in ws:
                if msg.type == WSMsgType.BINARY:
                    if rtc:
                        break
                    camera.transport = "JPEG compatibility"
                    try:
                        await asyncio.to_thread(camera.accept, msg.data)
                    except Exception:
                        await ws.close(code=1003, message=b"Invalid camera frame")
                        break
                    await ws.send_str("ack")
                elif msg.type == WSMsgType.TEXT and msg.data == "pause":
                    camera.clear()
                elif msg.type == WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        if isinstance(data, dict) and data.get("type") == "offer" and rtc is None:
                            rtc = Receiver(camera, ws)
                            await rtc.offer(data)
                        elif isinstance(data, dict) and data.get("type") == "settings":
                            if "flip" in data:
                                apply_flip(data["flip"])
                            await send_settings(ws)
                        else:
                            raise ValueError("Unexpected signaling message")
                    except Exception as exc:
                        print(f"Signaling failed: {type(exc).__name__}", flush=True)
                        await ws.close(code=1003, message=b"Invalid signaling")
                        break
                elif msg.type == WSMsgType.ERROR:
                    break
        finally:
            if rtc:
                await rtc.close()
            if producer is ws:
                producer = None
                camera.clear()
        return ws

    app = web.Application(middlewares=[headers], client_max_size=1024 * 1024)
    for path, name in {
        "/": "phone.html",
        "/legacy": "phone.html",
        "/phone.js": "phone.js",
        "/phone-mirror.js": "phone-mirror.js",
        "/style.css": "style.css",
        "/favicon.svg": "favicon.svg",
    }.items():
        app.router.add_get(path, file_handler(name))

    async def release_producer(application):
        if producer is not None:
            await producer.close()

    app.on_shutdown.append(release_producer)
    app.router.add_get("/stream", stream)
    app.router.add_get("/token-check", token_check)

    async def config(request):
        return web.Response(
            body=profile,
            content_type="application/x-apple-aspen-config",
            headers={"Content-Disposition": 'attachment; filename="PocketLens.mobileconfig"'},
        )

    setupapp = web.Application(middlewares=[headers])
    setupapp.router.add_get("/", file_handler("setup.html"))
    setupapp.router.add_get("/PocketLens.mobileconfig", config)
    setupapp.router.add_get("/style.css", file_handler("style.css"))
    setupapp.router.add_get("/favicon.svg", file_handler("favicon.svg"))

    @web.middleware
    async def local_only(request, handler):
        if request.host not in ("127.0.0.1:8766", "localhost:8766"):
            raise web.HTTPForbidden()
        if request.method != "GET" and request.headers.get("Origin") not in (
            "http://127.0.0.1:8766",
            "http://localhost:8766",
        ):
            raise web.HTTPForbidden()
        return await handler(request)

    dashboard = web.Application(middlewares=[local_only, headers])
    dashboard.router.add_get("/", file_handler("dashboard.html"))
    dashboard.router.add_get("/dashboard.js", file_handler("dashboard.js"))
    dashboard.router.add_get("/style.css", file_handler("style.css"))
    dashboard.router.add_get("/favicon.svg", file_handler("favicon.svg"))
    dashboard.router.add_get("/camera-test", file_handler("camera-test.html"))
    dashboard.router.add_get("/camera-test.js", file_handler("camera-test.js"))

    async def status(request):
        return web.json_response(
            {
                **camera.status(),
                "phoneUrl": phone_url,
                "setupUrl": setup_url,
                "ip": ip,
                "fingerprint": fingerprint,
                "app": "pocketlens",
                "cameraName": NAME,
                "version": (BASE / "VERSION").read_text().strip(),
            }
        )

    async def qr(request):
        data = io.BytesIO()
        qrcode.make(setup_url if request.query.get("type") == "setup" else phone_url).save(
            data, format="PNG"
        )
        return web.Response(body=data.getvalue(), content_type="image/png")

    async def preview_stream(request):
        response = web.StreamResponse(
            headers={
                "Content-Type": "multipart/x-mixed-replace; boundary=frame",
                "Cache-Control": "no-store",
            }
        )
        await response.prepare(request)
        # Re-encode only when the shared frame, flip, or liveness changes; an idle
        # preview stream should not burn CPU on identical JPEGs.
        sent = None
        try:
            while not stop.is_set():
                transport = request.transport
                if transport is None or transport.is_closing():
                    break
                frame, state = camera.snapshot()
                if state != sent:
                    sent = state
                    _, jpeg = await asyncio.to_thread(
                        cv2.imencode, ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 65]
                    )
                    body = jpeg.tobytes()
                    await asyncio.wait_for(
                        response.write(
                            b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                            + str(len(body)).encode()
                            + b"\r\n\r\n"
                            + body
                            + b"\r\n"
                        ),
                        timeout=1,
                    )
                await asyncio.sleep(1 / 15)
        except (ConnectionError, asyncio.TimeoutError):
            pass
        return response

    async def settings(request):
        try:
            data = await request.json()
        except (ValueError, UnicodeError):
            raise web.HTTPBadRequest(text="Expected JSON settings")
        if not isinstance(data, dict) or type(data.get("flip")) is not bool:
            raise web.HTTPBadRequest(text="flip must be boolean")
        apply_flip(data["flip"])
        await send_settings(producer)
        return web.json_response({"flip": camera.flip})

    async def shutdown(request):
        stop.set()
        return web.json_response({"stopped": True})

    dashboard.router.add_get("/status", status)
    dashboard.router.add_get("/qr", qr)
    dashboard.router.add_get("/preview-stream", preview_stream)
    dashboard.router.add_post("/settings", settings)
    dashboard.router.add_post("/shutdown", shutdown)
    return app, setupapp, dashboard


async def run(args):
    # Preserve the pre-PocketLens pairing CA before creating certificates.
    state_directory(data_directory())
    ip = str(ipaddress.IPv4Address(args.ip or lan_ip()))
    profile, fingerprint = certificates(ip)
    register()
    camera = Camera()
    try:
        settings = json.loads((STATE / "settings.json").read_text())
        if isinstance(settings, dict):
            camera.flip = settings.get("flip") is True
    except (FileNotFoundError, ValueError):
        pass
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    previous_handlers = {}
    for sig in (signal.SIGINT, signal.SIGTERM):
        previous_handlers[sig] = signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))
    runners = []
    try:
        app, setupapp, dashboard = create_apps(
            camera, ip, profile, fingerprint, secrets.token_urlsafe(32), stop
        )
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(STATE / "server.pem", STATE / "server-key.pem")
        for application, host, port, tls in [
            (app, "0.0.0.0", 8765, ctx),
            (setupapp, "0.0.0.0", 8764, None),
            (dashboard, "127.0.0.1", 8766, None),
        ]:
            runner = web.AppRunner(application, access_log=None)
            await runner.setup()
            runners.append(runner)
            await web.TCPSite(runner, host, port, ssl_context=tls).start()
        # The local dashboard provides the pairing secret; don't put it in logs.
        print(f"PocketLens running. Dashboard: http://127.0.0.1:8766 | LAN: {ip}", flush=True)
        if not args.no_browser:
            webbrowser.open("http://127.0.0.1:8766")
        await stop.wait()
    finally:
        for runner in reversed(runners):
            await runner.cleanup()
        camera.close()
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--ip")
    p.add_argument("--no-browser", action="store_true")
    args = p.parse_args()
    asyncio.run(run(args))
