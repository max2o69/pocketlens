const live = document.querySelector("#live"),
  consumer = document.querySelector("#consumer");
let previous = null,
  previousTime = performance.now(),
  stopped = false;
async function update() {
  if (stopped) return;
  try {
    const response = await fetch("/status");
    if (!response.ok) throw Error("Receiver unavailable");
    const s = await response.json(),
      now = performance.now(),
      fps =
        previous === null
          ? null
          : Math.max(0, ((s.frames - previous) * 1000) / (now - previousTime));
    previous = s.frames;
    previousTime = now;
    live.innerHTML = `<i class="dot"></i>${s.live ? "iPhone live" + (fps === null ? "" : " · " + fps.toFixed(0) + " fps") : "Waiting for iPhone"}`;
    live.className = s.live ? "live" : "";
    consumer.textContent = s.cameraInUse
      ? "Windows camera is in use"
      : "No meeting app connected";
    document.querySelector("#ip").textContent = "Laptop address: " + s.ip;
    document.querySelector("#transport").textContent = s.transport || "Waiting";
    document.querySelector("#fingerprint").textContent = s.fingerprint
      .match(/.{1,2}/g)
      .join(":");
    document.querySelector("#version").textContent = "v" + s.version;
    document.querySelector("#flip").checked = !!s.flip;
    document.querySelector("#serverMessage").textContent = "";
  } catch (e) {
    document.querySelector("#serverMessage").textContent =
      "Receiver stopped. Run Start PocketLens.cmd to reconnect.";
  }
  setTimeout(update, 1000);
}
document.querySelector("#shutdown").onclick = async () => {
  try {
    await fetch("/shutdown", { method: "POST" });
    stopped = true;
    document.querySelector("#serverMessage").textContent = "Receiver stopped.";
    live.textContent = "Offline";
    consumer.textContent = "";
    document.querySelector("#shutdown").disabled = true;
  } catch (e) {
    document.querySelector("#serverMessage").textContent =
      "Receiver is already offline.";
  }
};
update();
document.querySelector("#flip").onchange = async (event) => {
  const control = event.target;
  control.disabled = true;
  try {
    const response = await fetch("/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ flip: control.checked }),
    });
    if (!response.ok) throw Error("Could not save orientation");
  } catch (e) {
    control.checked = !control.checked;
    document.querySelector("#serverMessage").textContent =
      "Could not change orientation. Please retry.";
  } finally {
    control.disabled = false;
  }
};
