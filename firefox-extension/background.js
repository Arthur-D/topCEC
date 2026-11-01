// SPDX-License-Identifier: GPL-3.0-or-later
/* Only audible/muted flags and active tab titles are sent to the local host. */
const NATIVE_HOST = "net.local.topcec.media";
const SNAPSHOT_INTERVAL_MS = 2000;
const RETRY_INTERVAL_MS = 2000;
let nativePort = null;
let retryTimer = null;
let snapshotTimer = null;

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
            windows: windows.map((window) => {
                const tabs = window.tabs || [];
                const activeTab = tabs.find((tab) => tab.active);
                return {
                    window_id: window.id,
                    active_title: activeTab ? (activeTab.title || "") : "",
                    tabs: tabs.map((tab) => ({
                        audible: tab.audible === true,
                        muted: tab.mutedInfo ? tab.mutedInfo.muted === true : false
                    }))
                };
            })
        };
        if (nativePort) {
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
