// SPDX-License-Identifier: GPL-3.0-or-later
const HOST = "net.local.topcec.media";
let port = null;
let retry = null;

function connect() {
    if (port) return true;
    try {
        port = chrome.runtime.connectNative(HOST);
        port.onDisconnect.addListener(() => {
            console.error("topCEC native host disconnected:", chrome.runtime.lastError?.message);
            port = null;
            schedule();
        });
        port.onMessage.addListener(message => {
            if (!message || message.accepted !== true)
                console.error("topCEC native host rejected a media snapshot");
        });
        return true;
    } catch (error) {
        console.error("topCEC native host unavailable:", error);
        schedule();
        return false;
    }
}

function schedule() {
    if (!retry) retry = setTimeout(() => {
        retry = null;
        publish();
    }, 2000);
}

function publish() {
    if (!connect()) return;
    chrome.windows.getAll({populate: true, windowTypes: ["normal"]}, windows => {
        if (chrome.runtime.lastError) {
            console.error("topCEC cannot read browser windows:", chrome.runtime.lastError.message);
            schedule();
            return;
        }
        const snapshot = {
            version: 1,
            windows: windows.map(window => {
                const tabs = window.tabs || [];
                const active = tabs.find(tab => tab.active);
                return {
                    window_id: window.id,
                    active_title: active ? (active.title || "") : "",
                    tabs: tabs.map(tab => ({
                        audible: typeof tab.audible === "boolean" ? tab.audible : null,
                        muted: typeof tab.mutedInfo?.muted === "boolean"
                            ? tab.mutedInfo.muted : null
                    }))
                };
            })
        };
        if (port) port.postMessage(snapshot);
    });
}

chrome.tabs.onUpdated.addListener((_id, change) => {
    if (["audible", "mutedInfo", "title", "status", "windowId"].some(
            key => Object.prototype.hasOwnProperty.call(change, key))) publish();
});
chrome.tabs.onActivated.addListener(publish);
chrome.tabs.onCreated.addListener(publish);
chrome.tabs.onRemoved.addListener(publish);
chrome.tabs.onAttached.addListener(publish);
chrome.tabs.onDetached.addListener(publish);
chrome.windows.onCreated.addListener(publish);
chrome.windows.onRemoved.addListener(publish);
chrome.runtime.onStartup.addListener(publish);
chrome.runtime.onInstalled.addListener(publish);
setInterval(publish, 2000);
publish();
