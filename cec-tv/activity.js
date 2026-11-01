// SPDX-License-Identifier: GPL-3.0-or-later
let lastOutput = "";
let lastMouseReport = 0;
let lastMouseOutput = "";
let watchedScreens = [];
function send(message) {
    callDBus("net.local.CecActivity", "/net/local/CecActivity", "net.local.CecActivity", "Report", message);
}
function outputAt(pos) {
    const screens = workspace.screens;
    let match = null;
    for (let i = 0; i < screens.length; i++) {
        // KWin's script rectangle exposes fields, not QRect.contains().
        // Half-open bounds give adjacent outputs an unambiguous shared edge.
        const geometry = screens[i].geometry;
        if (pos.x >= geometry.x && pos.x < geometry.x + geometry.width &&
            pos.y >= geometry.y && pos.y < geometry.y + geometry.height) {
            if (match !== null) return "unknown";
            match = screens[i];
        }
    }
    return match ? match.name : "unknown";
}
function updateCursorOutput() {
    const output = outputAt(workspace.cursorPos);
    if (output !== lastOutput) {
        lastOutput = output;
        send("Mus: " + output);
    }
    return output;
}
function watchScreens() {
    const screens = workspace.screens;
    for (let i = 0; i < screens.length; i++) {
        if (watchedScreens.indexOf(screens[i]) === -1) {
            screens[i].geometryChanged.connect(updateCursorOutput);
            watchedScreens.push(screens[i]);
        }
    }
    watchedScreens = watchedScreens.filter(function (watched) {
        for (let i = 0; i < screens.length; i++) {
            if (screens[i] === watched) return true;
        }
        return false;
    });
}
function refreshScreens() {
    watchScreens();
    updateCursorOutput();
}
function reportCursor() {
    const output = updateCursorOutput();
    if (output !== "unknown" &&
            (output !== lastMouseOutput || Date.now() - lastMouseReport >= 1000)) {
        lastMouseReport = Date.now();
        lastMouseOutput = output;
        send("Mouse-activity: " + output);
    }
}
function reportFocus() {
    const window = workspace.activeWindow;
    const output = window && window.output ? window.output.name : "ingen";
    send("Fokus: " + output);
}
workspace.cursorPosChanged.connect(reportCursor);
workspace.screensChanged.connect(refreshScreens);
workspace.windowActivated.connect(reportFocus);
watchScreens();
reportCursor();
reportFocus();
