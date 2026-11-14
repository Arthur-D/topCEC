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

browser.runtime.onMessage.addListener((message) => {
    if (message === "topcec-video-state") {
        return Promise.resolve({
            playing: playingVideo(document)
        });
    }
});
