// Run through Test PocketLens Browser.ps1 after building the native camera.
// Synthetic phone capture; actual native virtual-webcam consumer.
async function phoneMirrorCompatibility(page) {
  const base = new URL(page.url()).origin;
  const original = await (await page.request.get(base + "/status")).json();
  const phone = await page.context().newPage();
  const errors = [];
  phone.on("pageerror", (error) => errors.push(error.message));
  const setFlip = async (flip) => {
    const response = await page.request.post(base + "/settings", {
      headers: { Origin: base },
      data: { flip },
    });
    if (!response.ok()) throw Error("Could not change outgoing orientation");
  };
  const checkOutput = async (mirrored) => {
    await page.waitForFunction((flipped) => {
      const video = document.querySelector("#test-video");
      if (!video.videoWidth) return false;
      const canvas = document.createElement("canvas");
      canvas.width = 1280;
      canvas.height = 720;
      const paint = canvas.getContext("2d", { willReadFrequently: true });
      paint.drawImage(video, 0, 0, 1280, 720);
      const left = paint.getImageData(200, 400, 1, 1).data;
      const right = paint.getImageData(1000, 400, 1, 1).data;
      return flipped
        ? left[2] > 200 && right[0] > 200
        : left[0] > 200 && right[2] > 200;
    }, mirrored);
  };
  const checkPreview = async (mirrored) => {
    await phone.waitForFunction((flipped) => {
      const control = document.querySelector("#mirror");
      const video = document.querySelector("#video");
      const transform = new DOMMatrix(getComputedStyle(video).transform);
      return (
        control.checked === flipped && transform.a === (flipped ? -1 : 1)
      );
    }, mirrored);
  };
  try {
    await phone.addInitScript(
      (secret) => sessionStorage.setItem("pairing", secret),
      original.phoneUrl.split("#")[1],
    );
    await phone.addInitScript(() => {
      // Exercise the real phone scripts without opening a physical camera.
      navigator.mediaDevices.getUserMedia = async () => {
        const canvas = document.createElement("canvas");
        canvas.width = 1280;
        canvas.height = 720;
        const paint = canvas.getContext("2d");
        const draw = () => {
          paint.fillStyle = "red";
          paint.fillRect(0, 0, 640, 720);
          paint.fillStyle = "blue";
          paint.fillRect(640, 0, 640, 720);
          paint.fillStyle = "white";
          paint.fillText(String(Date.now()), 20, 50);
        };
        draw();
        const timer = setInterval(draw, 33);
        const capture = canvas.captureStream(30);
        capture.getVideoTracks()[0].addEventListener("ended", () =>
          clearInterval(timer),
        );
        window.mirrorSource = { capture, timer };
        return capture;
      };
    });
    await page.goto(base + "/camera-test");
    await page.getByRole("button", { name: "Test webcam", exact: true }).click();
    const results = {};
    for (const [mode, path] of [["WebRTC", "/"], ["JPEG", "/legacy"]]) {
      await setFlip(false);
      await phone.goto(new URL(path, original.phoneUrl.split("#")[0]).href);
      await phone.getByLabel("Camera", { exact: true }).selectOption("user");
      // A change while stopped must be applied on the next connection.
      await phone.getByRole("checkbox", { name: "Mirror video", exact: true }).check();
      await phone.getByRole("button", { name: "Start camera", exact: true }).click();
      await phone.waitForFunction(() =>
        document.querySelector("#status").textContent.startsWith("Live"),
      );
      await checkPreview(true);
      await checkOutput(true);
      await phone.getByRole("checkbox", { name: "Mirror video", exact: true }).uncheck();
      await checkPreview(false);
      await checkOutput(false);
      await phone.getByRole("checkbox", { name: "Mirror video", exact: true }).check();
      await checkPreview(true);
      await checkOutput(true);
      // Dashboard updates must update the phone too, without a second flip.
      await setFlip(false);
      await checkPreview(false);
      await checkOutput(false);
      await phone.getByRole("button", { name: "Stop camera", exact: true }).click();
      await phone.evaluate(() => clearInterval(window.mirrorSource.timer));
      await phone.getByRole("button", { name: "Start camera", exact: true }).click();
      await phone.waitForFunction(() =>
        document.querySelector("#status").textContent.startsWith("Live"),
      );
      await checkPreview(false);
      await checkOutput(false);
      await phone.getByRole("button", { name: "Stop camera", exact: true }).click();
      await phone.evaluate(() => {
        clearInterval(window.mirrorSource.timer);
        if (window.mirrorSource.capture.getTracks().some((track) => track.readyState !== "ended"))
          throw Error("Phone capture remained active after Stop camera");
      });
      results[mode] = { preview: true, outgoing: true, dashboardSync: true, stopStart: true };
    }
    if (errors.length) throw Error("Phone script errors: " + errors.join(", "));
    return { ...results, pageErrors: errors.length };
  } finally {
    await phone.getByRole("button", { name: "Stop camera", exact: true }).click().catch(() => {});
    await phone.evaluate(() => {
      if (window.mirrorSource) {
        clearInterval(window.mirrorSource.timer);
        window.mirrorSource.capture.getTracks().forEach((track) => track.stop());
      }
    }).catch(() => {});
    await phone.close();
    await page.getByRole("button", { name: "Stop test", exact: true }).click().catch(() => {});
    await setFlip(original.flip);
  }
}
