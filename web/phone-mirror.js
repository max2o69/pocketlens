// Both phone transports share the receiver's outgoing flip setting.
window.phoneMirror = (() => {
  const control = document.querySelector("#mirror");
  const preview = document.querySelector("#video");
  let socket = null;
  let pending = false;

  function render() {
    preview.classList.toggle("mirrored", control.checked);
  }

  control.onchange = () => {
    render();
    pending = true;
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: "settings", flip: control.checked }));
    }
  };
  render();

  return {
    connect(connection) {
      socket = connection;
      socket.send(
        JSON.stringify(
          pending
            ? { type: "settings", flip: control.checked }
            : { type: "settings" },
        ),
      );
    },
    disconnect() {
      socket = null;
    },
    receive(text, connection) {
      if (connection !== socket) return false;
      let data;
      try {
        data = JSON.parse(text);
      } catch {
        return false;
      }
      if (data?.type !== "settings" || typeof data.flip !== "boolean")
        return false;
      control.checked = data.flip;
      pending = false;
      render();
      return true;
    },
  };
})();
