const video = document.querySelector("#video"),
  statusEl = document.querySelector("#status");
const startBtn = document.querySelector("#start"),
  stopBtn = document.querySelector("#stop");
const lens = document.querySelector("#lens"),
  quality = document.querySelector("#quality");
const token = location.hash.slice(1) || sessionStorage.getItem("pairing");
if (token) {
  sessionStorage.setItem("pairing", token);
  history.replaceState(null, "", location.pathname);
}
let stream = null,
  ws = null,
  pc = null,
  wake = null,
  active = false,
  epoch = 0,
  failures = 0,
  retryTimer = null,
  statsTimer = null,
  timeout = null,
  frameTimer = null,
  ackTimer = null,
  lastFrameAt = 0,
  lastVideoTime = -1,
  lastAdvance = 0;
const legacy = location.pathname === "/legacy";
const canvas = legacy ? document.createElement("canvas") : null;
const ctx = canvas?.getContext("2d", { alpha: false });
if (canvas) {
  canvas.width = 1280;
  canvas.height = 720;
}
function message(text, error = false) {
  statusEl.textContent = text;
  statusEl.className = "message" + (error ? " error" : "");
}
async function keepAwake() {
  try {
    if (navigator.wakeLock && document.visibilityState === "visible")
      wake = await navigator.wakeLock.request("screen");
  } catch {}
}
async function pairingRejected() {
  // The receiver issues a new pairing token each start; a 403 means this one is stale.
  try {
    const response = await fetch(
      "/token-check?token=" + encodeURIComponent(token),
      { cache: "no-store" },
    );
    return response.status === 403;
  } catch {
    return false;
  }
}
const modeLink = document.querySelector("#legacy");
modeLink.href = legacy ? "/" : "/legacy";
modeLink.textContent = legacy ? "Use WebRTC" : "Use JPEG compatibility mode";
modeLink.onclick = stopCamera;
function closeConnection() {
  phoneMirror.disconnect();
  clearTimeout(timeout);
  clearTimeout(frameTimer);
  clearTimeout(ackTimer);
  clearInterval(statsTimer);
  if (ws) {
    ws.onclose = null;
    ws.close();
    ws = null;
  }
  if (pc) {
    pc.onconnectionstatechange = null;
    pc.close();
    pc = null;
  }
}
function stopCamera() {
  active = false;
  epoch++;
  clearTimeout(retryTimer);
  closeConnection();
  if (stream) {
    stream.getTracks().forEach((t) => {
      t.onended = null;
      t.stop();
    });
    stream = null;
  }
  video.srcObject = null;
  if (wake) {
    wake.release().catch(() => {});
    wake = null;
  }
  startBtn.disabled = false;
  stopBtn.disabled = true;
  lens.disabled = false;
  quality.disabled = false;
  message("Camera is off.");
}
async function retry(current) {
  if (!active || current !== epoch) return;
  const retryEpoch = ++epoch;
  closeConnection();
  failures++;
  if (failures >= 2 && (await pairingRejected())) {
    if (!active || retryEpoch !== epoch) return;
    sessionStorage.removeItem("pairing");
    stopCamera();
    message(
      "Pairing code changed. Scan the new QR code on your laptop, then tap Start camera.",
      true,
    );
    return;
  }
  if (!active || retryEpoch !== epoch) return;
  message("Reconnecting… Keep Safari open.", true);
  retryTimer = setTimeout(connect, Math.min(5000, 1000 * failures));
}
async function waitForIce(peer) {
  if (peer.iceGatheringState === "complete") return;
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      peer.removeEventListener("icegatheringstatechange", check);
      reject(Error("Could not discover a local network route."));
    }, 8000);
    function check() {
      if (peer.iceGatheringState === "complete") {
        clearTimeout(timer);
        peer.removeEventListener("icegatheringstatechange", check);
        resolve();
      }
    }
    peer.addEventListener("icegatheringstatechange", check);
    check();
  });
}
async function showStats(peer, current) {
  if (current !== epoch || !active) return;
  if (stream?.getVideoTracks()[0]?.readyState !== "live") {
    stopCamera();
    message("Camera access ended. Tap Start camera.", true);
    return;
  }
  try {
    const stats = await peer.getStats();
    let rtt = null,
      fps = null;
    stats.forEach((s) => {
      if (s.type === "candidate-pair" && s.state === "succeeded" && s.nominated)
        rtt = s.currentRoundTripTime;
      if (s.type === "outbound-rtp" && s.kind === "video")
        fps = s.framesPerSecond;
    });
    if (peer.connectionState === "connected")
      message(
        `Live · WebRTC${fps ? " · " + Math.round(fps) + " fps" : ""}${rtt != null ? " · network RTT " + Math.round(rtt * 1000) + " ms" : ""}`,
      );
  } catch {}
}
function connect() {
  if (!active) return;
  const current = ++epoch;
  const socket = new WebSocket(
    `wss://${location.host}/stream?token=${encodeURIComponent(token)}`,
  );
  ws = socket;
  socket.onclose = () => retry(current);
  socket.onerror = () => {
    if (current === epoch) message("Connection interrupted. Trying again…", true);
  };
  if (!legacy) {
    connectRTC(socket, current);
    return;
  }
  socket.onopen = () => {
    if (current !== epoch) return;
    failures = 0;
    phoneMirror.connect(socket);
    message("Connected. Sending to your laptop.");
    sendFrame();
  };
  socket.onmessage = (event) => {
    if (current !== epoch) return;
    if (phoneMirror.receive(event.data, socket) || event.data !== "ack") return;
    clearTimeout(ackTimer);
    message(`Live · 1280 × 720 · ${quality.value} fps target`);
    schedule();
  };
}
function connectRTC(socket, current) {
  const peer = new RTCPeerConnection({
    iceServers: [],
    bundlePolicy: "max-bundle",
  });
  pc = peer;
  const sender = peer.addTrack(stream.getVideoTracks()[0], stream);
  const transceiver = peer.getTransceivers()[0];
  const codecs = RTCRtpSender.getCapabilities?.("video")?.codecs;
  if (codecs && transceiver.setCodecPreferences) {
    const h264 = codecs.filter(
      (c) => c.mimeType.toLowerCase() === "video/h264",
    );
    if (h264.length)
      transceiver.setCodecPreferences([
        ...h264,
        ...codecs.filter((c) => c.mimeType.toLowerCase() !== "video/h264"),
      ]);
  }
  timeout = setTimeout(() => {
    if (current === epoch) {
      stopCamera();
      message(
        "WebRTC could not connect. Check the firewall or use JPEG compatibility below.",
        true,
      );
    }
  }, 15000);
  socket.onopen = async () => {
    try {
      if (current !== epoch) return;
      failures = 0;
      phoneMirror.connect(socket);
      await peer.setLocalDescription(await peer.createOffer());
      await waitForIce(peer);
      if (current !== epoch) return;
      socket.send(
        JSON.stringify({ type: "offer", sdp: peer.localDescription.sdp }),
      );
    } catch (e) {
      if (current === epoch) {
        stopCamera();
        message(e.message, true);
      }
    }
  };
  socket.onmessage = async (event) => {
    if (current !== epoch) return;
    if (phoneMirror.receive(event.data, socket)) return;
    try {
      const data = JSON.parse(event.data);
      if (data.type === "answer") {
        await peer.setRemoteDescription(data);
        const params = sender.getParameters();
        if (params.encodings?.length) {
          params.encodings[0].maxBitrate =
            Number(quality.value) === 15 ? 1000000 : 2500000;
          await sender.setParameters(params).catch(() => {});
        }
      }
    } catch (e) {
      if (current === epoch) {
        stopCamera();
        message("Connection failed: " + e.message, true);
      }
    }
  };
  peer.onconnectionstatechange = () => {
    if (current !== epoch) return;
    if (peer.connectionState === "connected") {
      clearTimeout(timeout);
      message("Live · WebRTC");
      clearInterval(statsTimer);
      statsTimer = setInterval(() => showStats(peer, current), 1000);
    } else if (peer.connectionState === "failed") retry(current);
  };
}
function schedule() {
  if (active)
    frameTimer = setTimeout(
      sendFrame,
      Math.max(
        0,
        1000 / Number(quality.value) - (performance.now() - lastFrameAt),
      ),
    );
}
function sendFrame() {
  if (!active || !ws || ws.readyState !== WebSocket.OPEN) return;
  if (stream?.getVideoTracks()[0]?.readyState !== "live") {
    stopCamera();
    message("Camera access ended. Tap Start camera to reconnect.", true);
    return;
  }
  if (!video.videoWidth || video.readyState < 2) {
    frameTimer = setTimeout(sendFrame, 100);
    return;
  }
  if (video.currentTime === lastVideoTime) {
    if (performance.now() - lastAdvance > 2000)
      message(
        "Camera paused. Keep Safari visible, or tap Stop then Start.",
        true,
      );
    frameTimer = setTimeout(sendFrame, 10);
    return;
  }
  lastVideoTime = video.currentTime;
  lastAdvance = performance.now();
  const current = epoch,
    socket = ws;
  // Fit rather than crop, preserving orientation without stretching faces.
  const scale = Math.min(1280 / video.videoWidth, 720 / video.videoHeight),
    w = Math.round(video.videoWidth * scale),
    h = Math.round(video.videoHeight * scale);
  ctx.fillStyle = "#080e0a";
  ctx.fillRect(0, 0, 1280, 720);
  ctx.drawImage(video, (1280 - w) / 2, (720 - h) / 2, w, h);
  lastFrameAt = performance.now();
  canvas.toBlob(
    (blob) => {
      if (
        current !== epoch ||
        !active ||
        !blob ||
        socket.readyState !== WebSocket.OPEN
      )
        return;
      socket.send(blob);
      ackTimer = setTimeout(() => socket.close(), 4000);
    },
    "image/jpeg",
    Number(quality.value) === 15 ? 0.76 : 0.88,
  );
}
startBtn.onclick = async () => {
  if (!token) {
    message("Scan the pairing QR code on your laptop first.", true);
    return;
  }
  if (!navigator.mediaDevices?.getUserMedia) {
    message("Complete the HTTPS certificate setup, then reopen Safari.", true);
    return;
  }
  const current = ++epoch;
  startBtn.disabled = true;
  stopBtn.disabled = false;
  message("Requesting camera access…");
  try {
    const captured = await navigator.mediaDevices.getUserMedia({
      audio: false,
      video: {
        facingMode: { ideal: lens.value },
        width: { ideal: 1280, max: 1280 },
        height: { ideal: 720, max: 720 },
        frameRate: { ideal: Number(quality.value), max: Number(quality.value) },
      },
    });
    if (current !== epoch) {
      captured.getTracks().forEach((track) => track.stop());
      return;
    }
    stream = captured;
    video.srcObject = stream;
    await video.play();
    if (current !== epoch) return;
    active = true;
    failures = 0;
    lastVideoTime = -1;
    lastAdvance = performance.now();
    stopBtn.disabled = false;
    lens.disabled = true;
    quality.disabled = true;
    stream.getVideoTracks()[0].onended = () => {
      stopCamera();
      message("Camera access ended. Tap Start camera.", true);
    };
    await keepAwake();
    if (current !== epoch) return;
    message("Connecting video…");
    connect();
  } catch (e) {
    if (current === epoch) {
      stopCamera();
      message(
        e.name === "NotAllowedError"
          ? "Camera permission was denied. Allow camera access in Safari’s website settings, then try again."
          : "Could not start camera: " + e.message,
        true,
      );
    }
  }
};
stopBtn.onclick = stopCamera;
document.addEventListener("visibilitychange", () => {
  if (active && document.visibilityState === "visible") keepAwake();
});
window.addEventListener("pagehide", stopCamera);
