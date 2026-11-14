// SPDX-License-Identifier: GPL-3.0-or-later
/* Only media flags and active tab titles are sent to the local host. */
const NATIVE_HOST = "net.local.topcec.media";
const SNAPSHOT_INTERVAL_MS = 2000;
const RETRY_INTERVAL_MS = 2000;
let nativePort = null;
let retryTimer = null;
let snapshotTimer = null;
let snapshotSequence = 0;

async function withinTimeout(promise) {
    let timer;
    try {
        return await Promise.race([promise, new Promise((resolve) => {
            timer = setTimeout(() => resolve(null), 1000);
        })]);
    } finally {
        clearTimeout(timer);
    }
}

async function videoState(tabId) {
    try {
        const frames = await withinTimeout(browser.webNavigation.getAllFrames({tabId}));
        if (!frames || !frames.length) return null;
        const states = await Promise.all(frames.map(async (frame) => {
            try {
                const result = await withinTimeout(browser.tabs.sendMessage(
                    tabId, "topcec-video-state", {frameId: frame.frameId}));
                return typeof result?.playing === "boolean" ? result.playing : null;
            } catch (_error) {
                return null;
            }
        }));
        return states.some(Boolean) ? true : (states.includes(null) ? null : false);
    } catch (_error) {
        return null;
    }
}

function connect() {
    if (nativePort) {
        return true;
    }
    try {
        nativePort = browser.runtime.connectNative(NATIVE_HOST);
        nativePort.onDisconnect.addListener(() => {
            nativePort = null;
            scheduleReconnect();
        });
        nativePort.onMessage.addListener((message) => {
            if (!message || message.accepted !== true) {
                console.error("topCEC native host rejected a media snapshot");
            }
        });
        return true;
    } catch (error) {
        console.error("topCEC native host is unavailable:", error.message);
        scheduleReconnect();
        return false;
    }
}

function scheduleReconnect() {
    if (!retryTimer) {
        retryTimer = setTimeout(() => {
            retryTimer = null;
            publishSnapshot();
        }, RETRY_INTERVAL_MS);
    }
}

async function publishSnapshot() {
    const sequence = ++snapshotSequence;
    if (!connect()) {
        return;
    }
    try {
        const windows = await browser.windows.getAll({
            populate: true,
            windowTypes: ["normal"]
        });
        const snapshot = {
            version: 1,
            windows: await Promise.all(windows.map(async (window) => {
                const tabs = window.tabs || [];
                const activeTab = tabs.find((tab) => tab.active);
                return {
                    window_id: window.id,
                    active_title: activeTab ? (activeTab.title || "") : "",
                    tabs: await Promise.all(tabs.map(async (tab) => ({
                        audible: tab.audible === true,
                        muted: tab.mutedInfo ? tab.mutedInfo.muted === true : false,
                        video: await videoState(tab.id)
                    })))
                };
            }))
        };
        if (nativePort && sequence === snapshotSequence) {
            nativePort.postMessage(snapshot);
        }
    } catch (error) {
        console.error("topCEC could not read Firefox tab audio state:", error.message);
        nativePort = null;
        scheduleReconnect();
    }
}

function scheduleSnapshot() {
    if (snapshotTimer) {
        clearTimeout(snapshotTimer);
    }
    snapshotTimer = setTimeout(() => {
        snapshotTimer = null;
        publishSnapshot();
    }, 100);
}

browser.tabs.onUpdated.addListener((_tabId, changeInfo) => {
    if (["audible", "mutedInfo", "title", "status", "windowId"].some(
            (key) => Object.prototype.hasOwnProperty.call(changeInfo, key))) {
        scheduleSnapshot();
    }
});
browser.tabs.onActivated.addListener(scheduleSnapshot);
browser.tabs.onCreated.addListener(scheduleSnapshot);
browser.tabs.onRemoved.addListener(scheduleSnapshot);
browser.tabs.onAttached.addListener(scheduleSnapshot);
browser.tabs.onDetached.addListener(scheduleSnapshot);
browser.windows.onCreated.addListener(scheduleSnapshot);
browser.windows.onRemoved.addListener(scheduleSnapshot);
browser.runtime.onStartup.addListener(scheduleSnapshot);
browser.runtime.onInstalled.addListener(scheduleSnapshot);

setInterval(publishSnapshot, SNAPSHOT_INTERVAL_MS);
publishSnapshot();
