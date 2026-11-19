// SPDX-License-Identifier: GPL-3.0-or-later
let lastOutput = "";
let lastCursorPosition = null;
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
    const pos = workspace.cursorPos;
    lastCursorPosition = {x: pos.x, y: pos.y};
    const output = outputAt(lastCursorPosition);
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
    const previousPosition = lastCursorPosition;
    const output = updateCursorOutput();
    if (!previousPosition ||
            (previousPosition.x === lastCursorPosition.x &&
             previousPosition.y === lastCursorPosition.y)) return;
    // Use the same layout for both positions so a layout change alone
    // cannot move the pointer from one display to another.
    const previousOutput = outputAt(previousPosition);
    const crossed = previousOutput !== "unknown" && output !== previousOutput;
    if (output !== "unknown" &&
            (crossed || output !== lastMouseOutput || Date.now() - lastMouseReport >= 1000)) {
        lastMouseReport = Date.now();
        lastMouseOutput = output;
        if (crossed) {
            send(`Mouse-crossing: ${previousOutput} -> ${output} | cursor `
                 + `(${previousPosition.x}, ${previousPosition.y}) -> `
                 + `(${lastCursorPosition.x}, ${lastCursorPosition.y})`);
        } else {
            send("Mouse-activity: " + output);
        }
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
updateCursorOutput();
reportFocus();
