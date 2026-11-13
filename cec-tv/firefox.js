// SPDX-License-Identifier: GPL-3.0-or-later
// Temporary KWin 6 test bridge. Read-only: no CEC, window or audio changes.
// QTimer is provided by KWin's JavaScript engine, not a browser timer.
// https://invent.kde.org/plasma/kwin/-/blob/master/src/scripting/scripting.cpp
function send(message) {
    callDBus('net.local.CecActivity', '/net/local/CecActivity',
             'net.local.CecActivity', 'Report', message);
}
function reportFirefox() {
    try {
        const windows = workspace.windowList();
        const snapshot = [];
        for (let i = 0; i < windows.length; i++) {
            const w = windows[i];
            snapshot.push({pid: Number(w.pid), title: String(w.caption || ''),
                           output: w.output ? String(w.output.name) : 'ingen',
                           desktop: String(w.desktopFileName || ''),
                           class: String(w.resourceClass || '')});
        }
        // One atomic message also removes closed windows and old titles.
        send('Desktop-snapshot: ' + JSON.stringify(snapshot));
        const active = workspace.activeWindow;
        send('Fokus: ' + (active && active.output ? active.output.name : 'ingen'));
    } catch (error) {
        print('CEC_FIREFOX_LIVE: report failed: ' + error);
        // No partial snapshot. The monitor's freshness check blocks OFF.
    }
}
const heartbeat = new QTimer();
heartbeat.interval = 2000;
heartbeat.timeout.connect(reportFirefox);
workspace.windowActivated.connect(reportFirefox);
heartbeat.start();
reportFirefox();
print('CEC_FIREFOX_LIVE: started; snapshot every 2 seconds; no CEC');
