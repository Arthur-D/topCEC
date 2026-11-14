// SPDX-License-Identifier: GPL-3.0-or-later
function playingVideo(root) {
    for (const element of root.querySelectorAll("*")) {
        if (element.localName === "video" && !element.paused && !element.ended)
            return true;
        if (element.shadowRoot && playingVideo(element.shadowRoot))
            return true;
    }
    return false;
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message === "topcec-video-state") {
        sendResponse({
            playing: playingVideo(document)
        });
    }
});
