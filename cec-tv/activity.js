let lastOutput = "";
let lastMouseReport = 0;
function send(message) {
    callDBus("net.local.CecActivity", "/net/local/CecActivity", "net.local.CecActivity", "Report", message);
}
function reportCursor() {
    const pos = workspace.cursorPos;
    const output = pos.x >= 1536 ? "HDMI-A-2" : "HDMI-A-1";
    if (output !== lastOutput) {
        lastOutput = output;
        send("Mus: " + output);
    }
    if (output === "HDMI-A-2" && Date.now() - lastMouseReport >= 1000) {
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
workspace.windowActivated.connect(reportFocus);
reportCursor();
reportFocus();
