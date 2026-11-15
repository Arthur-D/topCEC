// SPDX-License-Identifier: GPL-3.0-or-later
function countPlayingVideos(root) {
    let count = 0;
    for (const element of root.querySelectorAll("*")) {
        if (element.localName === "video" && !element.paused && !element.ended)
            count++;
        const shadow = element.openOrClosedShadowRoot || element.shadowRoot;
        if (shadow)
            count += countPlayingVideos(shadow);
    }
    return count;
}

browser.runtime.onMessage.addListener((message) => {
    if (message === "topcec-video-state") {
        const count = countPlayingVideos(document);
        return Promise.resolve({
            playing: count > 0,
            count
        });
    }
});
