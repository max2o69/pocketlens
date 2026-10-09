// Run with playwright-cli run-code --filename scripts/browser_compatibility.js.
// Open /camera-test in an isolated Chrome profile with camera permission first.
// The producer is a synthetic canvas. The consumer opens only our real virtual camera.
async function browserCompatibility(page) {
  const base = new URL(page.url()).origin;
  const original = await (await page.request.get(base + "/status")).json();
  const phone = await page.context().newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  phone.on("pageerror", (error) => errors.push(error.message));
  const setFlip = async (flip) => {
    const response = await page.request.post(base + "/settings", {
      headers: { Origin: base },
      data: { flip },
    });
    if (!response.ok()) throw Error("Could not set outgoing orientation");
  };
  try {
    await setFlip(false);
    // Keep the pairing secret out of navigation errors and test logs.
    await phone.addInitScript(
      (secret) => sessionStorage.setItem("pairing", secret),
      original.phoneUrl.split("#")[1],
    );
    await phone.goto(original.phoneUrl.split("#")[0]);
    await phone.evaluate(async () => {
      const canvas = document.createElement("canvas");
      canvas.width = 1280;
      canvas.height = 720;
      const paint = canvas.getContext("2d");
      function draw() {
        paint.fillStyle = "red";
        paint.fillRect(0, 0, 640, 720);
        paint.fillStyle = "blue";
        paint.fillRect(640, 0, 640, 720);
        const stamp = Date.now() % 16777216;
        for (let bit = 0; bit < 24; bit++) {
          paint.fillStyle = (stamp >> bit) & 1 ? "white" : "black";
          paint.fillRect(bit * 40, 0, 40, 100);
        }
      }
      draw();
      const timer = setInterval(draw, 33);
      const capture = canvas.captureStream(30);
      const peer = new RTCPeerConnection({ iceServers: [] });
      peer.addTrack(capture.getVideoTracks()[0], capture);
      const secret = sessionStorage.getItem("pairing");
      const socket = new WebSocket(
        `wss://${location.host}/stream?token=${encodeURIComponent(secret)}`,
      );
      window.compatibilitySource = { peer, socket, capture, timer };
      const gathered = async () => {
        if (peer.iceGatheringState === "complete") return;
        await new Promise((resolve, reject) => {
          const timeout = setTimeout(
            () => reject(Error("ICE gathering timed out")),
            8000,
          );
          peer.addEventListener("icegatheringstatechange", () => {
            if (peer.iceGatheringState === "complete") {
              clearTimeout(timeout);
              resolve();
            }
          });
        });
      };
      await new Promise((resolve, reject) => {
        socket.onopen = async () => {
          try {
            await peer.setLocalDescription(await peer.createOffer());
            await gathered();
            socket.send(
              JSON.stringify({ type: "offer", sdp: peer.localDescription.sdp }),
            );
          } catch (error) {
            reject(error);
          }
        };
        socket.onmessage = async (event) => {
          try {
            const data = JSON.parse(event.data);
            if (data.type === "answer") {
              await peer.setRemoteDescription(data);
              resolve();
            }
          } catch (error) {
            reject(error);
          }
        };
        socket.onerror = () =>
          reject(Error("Synthetic sender could not connect"));
      });
    });
    await page.goto(base + "/camera-test");
    await page
      .getByRole("button", { name: "Test webcam", exact: true })
      .click();
    await page.waitForFunction(() =>
      document
        .querySelector("#test-metrics")
        .textContent.includes("browser frames received"),
    );
    const read = async () =>
      await page.evaluate(() => {
        const video = document.querySelector("#test-video");
        const canvas = document.createElement("canvas");
        canvas.width = 1280;
        canvas.height = 720;
        const paint = canvas.getContext("2d", { willReadFrequently: true });
        paint.drawImage(video, 0, 0, 1280, 720);
        let stamp = 0;
        for (let bit = 0; bit < 24; bit++) {
          if (paint.getImageData(bit * 40 + 20, 50, 1, 1).data[0] > 128)
            stamp |= 1 << bit;
        }
        return {
          width: video.videoWidth,
          height: video.videoHeight,
          left: Array.from(paint.getImageData(200, 400, 1, 1).data).slice(0, 3),
          right: Array.from(paint.getImageData(1000, 400, 1, 1).data).slice(
            0,
            3,
          ),
          age: (Date.now() - stamp + 16777216) % 16777216,
          frames: video.getVideoPlaybackQuality().totalVideoFrames,
        };
      });
    await page.waitForFunction(() => {
      const video = document.querySelector("#test-video");
      const canvas = document.createElement("canvas");
      canvas.width = 1280;
      canvas.height = 720;
      const paint = canvas.getContext("2d", { willReadFrequently: true });
      paint.drawImage(video, 0, 0);
      return paint.getImageData(200, 400, 1, 1).data[0] > 200;
    });
    const before = await read();
    if (
      before.width !== 1280 ||
      before.height !== 720 ||
      before.left[0] < 200 ||
      before.right[2] < 200
    ) {
      throw Error(
        "Virtual camera dimensions or RGB orientation were incorrect",
      );
    }
    const ages = [];
    let previousFrames = before.frames;
    for (let sample = 0; sample < 30; sample++) {
      await page.waitForTimeout(100);
      const frame = await read();
      ages.push(frame.age);
      if (frame.age > 1500)
        throw Error("Virtual camera stopped receiving fresh synthetic frames");
      previousFrames = frame.frames;
    }
    if (previousFrames <= before.frames + 20)
      throw Error("Browser frames did not keep advancing");
    await setFlip(true);
    await page.waitForFunction(() => {
      const video = document.querySelector("#test-video");
      const canvas = document.createElement("canvas");
      canvas.width = 1280;
      canvas.height = 720;
      const paint = canvas.getContext("2d", { willReadFrequently: true });
      paint.drawImage(video, 0, 0);
      return paint.getImageData(200, 400, 1, 1).data[2] > 200;
    });
    const flipped = await read();
    if (flipped.left[2] < 200 || flipped.right[0] < 200)
      throw Error("Actual webcam output did not flip");
    await page.getByRole("button", { name: "Stop test", exact: true }).click();
    await page
      .getByRole("button", { name: "Test webcam", exact: true })
      .click();
    await page.waitForFunction(() =>
      document
        .querySelector("#test-metrics")
        .textContent.includes("browser frames received"),
    );
    // Re-encode the real virtual webcam through a browser WebRTC connection.
    // This exercises the sending path used by browser meeting applications.
    const webRTCSend = await page.evaluate(async () => {
      const source = document.querySelector("#test-video").srcObject;
      const sending = new RTCPeerConnection({ iceServers: [] });
      const receiving = new RTCPeerConnection({ iceServers: [] });
      const remote = document.createElement("video");
      remote.muted = true;
      const gathered = async (peer) => {
        if (peer.iceGatheringState === "complete") return;
        await new Promise((resolve, reject) => {
          const timer = setTimeout(
            () => reject(Error("WebRTC ICE timed out")),
            8000,
          );
          peer.addEventListener("icegatheringstatechange", () => {
            if (peer.iceGatheringState === "complete") {
              clearTimeout(timer);
              resolve();
            }
          });
        });
      };
      try {
        const played = new Promise((resolve, reject) => {
          receiving.ontrack = (event) => {
            remote.srcObject = event.streams[0];
            remote.play().then(resolve, reject);
          };
        });
        sending.addTrack(source.getVideoTracks()[0], source);
        await sending.setLocalDescription(await sending.createOffer());
        await gathered(sending);
        await receiving.setRemoteDescription(sending.localDescription);
        await receiving.setLocalDescription(await receiving.createAnswer());
        await gathered(receiving);
        await sending.setRemoteDescription(receiving.localDescription);
        await played;
        await new Promise((resolve) =>
          remote.requestVideoFrameCallback(resolve),
        );
        const canvas = document.createElement("canvas");
        canvas.width = 1280;
        canvas.height = 720;
        const paint = canvas.getContext("2d", { willReadFrequently: true });
        paint.drawImage(remote, 0, 0, 1280, 720);
        const left = paint.getImageData(200, 400, 1, 1).data;
        const right = paint.getImageData(1000, 400, 1, 1).data;
        if (left[2] < 200 || right[0] < 200)
          throw Error("Browser WebRTC sending changed the webcam pixels");
        return true;
      } finally {
        remote.srcObject?.getTracks().forEach((track) => track.stop());
        sending.close();
        receiving.close();
        remote.srcObject = null;
      }
    });
    if (errors.length)
      throw Error("Browser script errors: " + errors.join(", "));
    ages.sort((a, b) => a - b);
    return {
      browser: await page.evaluate(() => navigator.userAgent),
      realVirtualCamera: true,
      dimensions: [before.width, before.height],
      movingPixels: true,
      flip: true,
      stopStart: true,
      webRTCSend,
      pageErrors: errors.length,
      syntheticFrameAgeMs: { median: ages[15], p95: ages[28], max: ages[29] },
      note: "Same-laptop synthetic canvas through WebRTC, Python, native virtual camera, and real browser capture. No physical camera or meeting call used.",
    };
  } finally {
    await page
      .getByRole("button", { name: "Stop test", exact: true })
      .click()
      .catch(() => {});
    await phone
      .evaluate(() => {
        const source = window.compatibilitySource;
        if (source) {
          clearInterval(source.timer);
          source.capture.getTracks().forEach((track) => track.stop());
          source.socket.close();
          source.peer.close();
        }
      })
      .catch(() => {});
    await phone.close();
    await setFlip(original.flip);
  }
}
