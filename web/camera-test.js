const video = document.querySelector("#test-video");
const start = document.querySelector("#test-start");
const stop = document.querySelector("#test-stop");
const message = document.querySelector("#test-message");
const metrics = document.querySelector("#test-metrics");
let stream = null;
let epoch = 0;
let frameCallback = null;
let watchdog = null;

function show(text, error = false) {
  message.textContent = text;
  message.className = "message" + (error ? " error" : "");
}

function stopTest() {
  epoch++;
  clearInterval(watchdog);
  if (frameCallback !== null && video.cancelVideoFrameCallback) {
    video.cancelVideoFrameCallback(frameCallback);
  }
  frameCallback = null;
  if (stream) {
    stream.getTracks().forEach((track) => {
      track.onended = null;
      track.stop();
    });
    stream = null;
  }
  video.srcObject = null;
  start.disabled = false;
  stop.disabled = true;
  metrics.textContent = "";
  show("Test stopped. The receiver can keep streaming to your meeting.");
}

start.onclick = async () => {
  if (!navigator.mediaDevices?.getUserMedia) {
    show(
      "Camera access is unavailable. Open this page from the laptop dashboard in Chrome or Edge.",
      true,
    );
    return;
  }
  const current = ++epoch;
  start.disabled = true;
  stop.disabled = false;
  metrics.textContent = "";
  show("Finding the virtual webcam…");
  let permissionStream = null;
  let opened = null;
  try {
    const response = await fetch("/status");
    if (!response.ok)
      throw Error("Receiver is unavailable. Run Start PocketLens.cmd.");
    const info = await response.json();
    const cameraName = info.cameraName;
    let devices = await navigator.mediaDevices.enumerateDevices();
    if (
      !devices.some((device) => device.kind === "videoinput" && device.label)
    ) {
      show("Allow camera access so the browser can list your webcams.");
      permissionStream = await navigator.mediaDevices.getUserMedia({
        video: true,
        audio: false,
      });
      devices = await navigator.mediaDevices.enumerateDevices();
    }
    if (current !== epoch) return;
    const camera = devices.find(
      (device) => device.kind === "videoinput" && device.label === cameraName,
    );
    if (!camera) {
      throw Error(
        "PocketLens was not found. Run Install PocketLens System Camera.cmd, restart your browser, and try again.",
      );
    }
    permissionStream?.getTracks().forEach((track) => track.stop());
    permissionStream = null;
    opened = await navigator.mediaDevices.getUserMedia({
      audio: false,
      video: {
        deviceId: { exact: camera.deviceId },
        width: { ideal: 1280 },
        height: { ideal: 720 },
      },
    });
    if (current !== epoch) return;
    stream = opened;
    video.srcObject = stream;
    await video.play();
    if (current !== epoch) return;
    let count = 0;
    let lastFrame = performance.now();
    const started = lastFrame;
    function received() {
      if (current !== epoch) return;
      count++;
      lastFrame = performance.now();
      metrics.textContent = `${video.videoWidth} × ${video.videoHeight} · ${count} browser frames received`;
      show(
        "This browser receives PocketLens. If you see the waiting screen, pair and start your phone.",
      );
      frameCallback = video.requestVideoFrameCallback(received);
    }
    if (video.requestVideoFrameCallback)
      frameCallback = video.requestVideoFrameCallback(received);
    else
      throw Error(
        "This browser cannot verify incoming video frames. Use a current version of Chrome or Edge.",
      );
    stream.getVideoTracks()[0].onended = () => {
      stopTest();
      show(
        "Webcam access ended. Restart the receiver and try the test again.",
        true,
      );
    };
    watchdog = setInterval(() => {
      if (current !== epoch) return;
      if (performance.now() - Math.max(started, lastFrame) > 5000) {
        stopTest();
        show(
          "The webcam opened but video frames stopped. Close other camera clients and retry.",
          true,
        );
      }
    }, 1000);
  } catch (error) {
    if (current === epoch) {
      stopTest();
      const help =
        error.name === "NotAllowedError"
          ? "Camera permission was denied. Allow camera access for this page in your browser, then retry."
          : error.name === "NotReadableError"
            ? "The webcam could not open. Close other camera clients, restart the receiver, and retry."
            : error.message;
      show(help, true);
    }
  } finally {
    permissionStream?.getTracks().forEach((track) => track.stop());
    if (opened && opened !== stream)
      opened.getTracks().forEach((track) => track.stop());
  }
};
stop.onclick = stopTest;
window.addEventListener("pagehide", stopTest);
