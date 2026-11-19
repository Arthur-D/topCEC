// SPDX-License-Identifier: GPL-3.0-or-later
let lastOutput = "";
let lastCursorPosition = null;
let lastMouseReport = 0;
let lastMouseOutput = "";
let pendingCrossing = null;
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
            screens[i].geometryChanged.connect(resetCursorOutput);
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
    resetCursorOutput();
}
function resetCursorOutput() {
    pendingCrossing = null;
    updateCursorOutput();
}
function withinSharedEdgePixel(previousOutput, output, entry, pos) {
    let previous, current, scale;
    for (const screen of workspace.screens) {
        if (screen.name === previousOutput) previous = screen.geometry;
        if (screen.name === output) {
            current = screen.geometry;
            scale = screen.devicePixelRatio;
        }
    }
    if (!previous || !current) return false;
    // KWin reports desktop coordinates in logical units.
    const pixel = Number.isFinite(scale) && scale > 0 ? 1 / scale : 1;
    const previousRight = previous.x + previous.width;
    const previousBottom = previous.y + previous.height;
    const right = current.x + current.width;
    const bottom = current.y + current.height;
    const besidePrevious = entry.y >= previous.y && entry.y < previousBottom;
    const aboveOrBelowPrevious = entry.x >= previous.x && entry.x < previousRight;
    return (besidePrevious && ((current.x === previousRight && pos.x < current.x + pixel)
                              || (right === previous.x && pos.x > right - pixel)))
        || (aboveOrBelowPrevious && ((current.y === previousBottom && pos.y < current.y + pixel)
                                    || (bottom === previous.y && pos.y > bottom - pixel)));
}
function reportCursor() {
    const previousPosition = lastCursorPosition;
    const output = updateCursorOutput();
    if (!previousPosition ||
            (previousPosition.x === lastCursorPosition.x &&
             previousPosition.y === lastCursorPosition.y)) return;
    // Use the same layout for both positions so a layout change alone
    // cannot move the pointer from one display to another.
    const previousOutput = pendingCrossing && output === pendingCrossing.origin
        ? output : outputAt(previousPosition);
    if (pendingCrossing && output !== pendingCrossing.destination) pendingCrossing = null;
    if (output !== "unknown" && previousOutput !== "unknown" && output !== previousOutput) {
        pendingCrossing = {origin: previousOutput, destination: output,
                           position: previousPosition, entry: lastCursorPosition};
    }
    const crossed = pendingCrossing &&
        !withinSharedEdgePixel(pendingCrossing.origin, output, pendingCrossing.entry,
                               lastCursorPosition);
    if (output !== "unknown" &&
            (crossed || output !== lastMouseOutput || Date.now() - lastMouseReport >= 1000)) {
        lastMouseReport = Date.now();
        lastMouseOutput = output;
        if (crossed) {
            const {origin, position} = pendingCrossing;
            pendingCrossing = null;
            send(`Mouse-crossing: ${origin} -> ${output} | cursor `
                 + `(${position.x}, ${position.y}) -> `
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
