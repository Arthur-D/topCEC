let lastOutput = "";
let lastMouseReport = 0;
let watchedScreens = [];
const TARGET = "HDMI-A-2";
function send(message) {
    callDBus("net.local.CecActivity", "/net/local/CecActivity", "net.local.CecActivity", "Report", message);
}
function outputAt(pos) {
    const screens = workspace.screens;
    let match = null;
    for (let i = 0; i < screens.length; i++) {
        if (screens[i].geometry.contains(pos)) {
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
    if (updateCursorOutput() === TARGET && Date.now() - lastMouseReport >= 1000) {
        lastMouseReport = Date.now();
        send("TV-aktivitet: mus");
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
