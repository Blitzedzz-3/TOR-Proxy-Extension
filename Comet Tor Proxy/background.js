const proxyHost = "127.0.0.1";
const proxyPort = 8080;

function enableProxy() {
  const config = {
    mode: "fixed_servers",
    rules: {
      singleProxy: { scheme: "http", host: proxyHost, port: proxyPort },
      bypassList: ["<local>"]
    }
  };
  chrome.proxy.settings.set({ value: config, scope: "regular" });
  chrome.storage.local.set({ proxyEnabled: true });
  console.log("Proxy enabled");
}

function disableProxy() {
  chrome.proxy.settings.clear({ scope: "regular" });
  chrome.storage.local.set({ proxyEnabled: false });
  console.log("Proxy disabled");
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.action === "connect") enableProxy();
  if (msg.action === "disconnect") disableProxy();
  sendResponse({ status: "ok" });
});

chrome.runtime.onInstalled.addListener(() => {
  chrome.storage.local.get(["proxyEnabled"], (data) => {
    if (data.proxyEnabled) enableProxy();
  });
});
