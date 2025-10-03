const connectBtn = document.getElementById("connectBtn");
const disconnectBtn = document.getElementById("disconnectBtn");
const statusSpan = document.getElementById("proxyStatus");

connectBtn.onclick = () => {
  chrome.runtime.sendMessage({ action: "connect" }, () => updateStatus());
};
disconnectBtn.onclick = () => {
  chrome.runtime.sendMessage({ action: "disconnect" }, () => updateStatus());
};

function updateStatus() {
  chrome.storage.local.get(["proxyEnabled"], (data) => {
    statusSpan.textContent = data.proxyEnabled ? "Connected" : "Disconnected";
  });
}

updateStatus();
