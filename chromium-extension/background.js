// SPDX-License-Identifier: GPL-3.0-or-later
const HOST = "net.local.topcec.media";
let port = null;
let retry = null;
let snapshotSequence = 0;

async function withinTimeout(promise) {
    let timer;
    try {
        return await Promise.race([promise, new Promise(resolve => {
            timer = setTimeout(() => resolve(null), 1000);
        })]);
    } finally {
        clearTimeout(timer);
    }
}

async function videoState(tabId) {
    try {
        const frames = await withinTimeout(chrome.webNavigation.getAllFrames({tabId}));
        if (!frames || !frames.length) return null;
        const states = await Promise.all(frames.map(async frame => {
            try {
                const result = await withinTimeout(chrome.tabs.sendMessage(
                    tabId, "topcec-video-state", {frameId: frame.frameId}));
                return typeof result?.playing === "boolean" ? result.playing : null;
            } catch (_error) {
                return null;
            }
        }));
        return states.includes(null) ? null : states.some(Boolean);
    } catch (_error) {
        return null;
    }
}

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

async function publish() {
    const sequence = ++snapshotSequence;
    if (!connect()) return;
    try {
        const windows = await chrome.windows.getAll({populate: true, windowTypes: ["normal"]});
        const snapshot = {
            version: 1,
            windows: await Promise.all(windows.map(async window => {
                const tabs = window.tabs || [];
                const active = tabs.find(tab => tab.active);
                return {
                    window_id: window.id,
                    active_title: active ? (active.title || "") : "",
                    tabs: await Promise.all(tabs.map(async tab => ({
                        audible: typeof tab.audible === "boolean" ? tab.audible : null,
                        muted: typeof tab.mutedInfo?.muted === "boolean"
                            ? tab.mutedInfo.muted : null,
                        video: await videoState(tab.id)
                    })))
                };
            }))
        };
        if (port && sequence === snapshotSequence) port.postMessage(snapshot);
    } catch (error) {
        console.error("topCEC cannot read browser windows:", error);
        schedule();
    }
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
