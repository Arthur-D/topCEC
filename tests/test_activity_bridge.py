"""Hardware-free KWin JavaScript tests; requires PySide6 (QtQml)."""
# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path
import json
import os
import unittest
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QJSEngine

APP = QGuiApplication.instance() or QGuiApplication([])
SOURCE = Path(__file__).resolve().parents[1] / 'cec-tv/activity.js'


class ActivityBridgeTests(unittest.TestCase):
    def evaluate(self, source):
        value = self.engine.evaluate(source)
        if value.isError():
            self.fail(value.toString())
        return value.toVariant()

    def setUp(self):
        self.engine = QJSEngine()
        self.evaluate('''
            var messages = [], now = 2000;
            Date.now = function () { return now; };
            function signal() {
                return { callbacks: [], connect: function (f) { this.callbacks.push(f); },
                    emit: function () { this.callbacks.forEach(function (f) { f(); }); } };
            }
            function screen(name, x, y, width, height) {
                // KWin exposes rectangle fields, without a contains() method.
                return { name: name, geometry: {x:x, y:y, width:width, height:height},
                    geometryChanged: signal() };
            }
            var workspace = {
                screens: [screen('HDMI-A-1',0,0,1536,864), screen('HDMI-A-2',1536,0,1920,1080)],
                cursorPos: {x:100, y:100}, activeWindow: null,
                cursorPosChanged: signal(), screensChanged: signal(), windowActivated: signal()
            };
            function callDBus(a,b,c,d,message) { messages.push(message); }
        ''')
        self.evaluate(SOURCE.read_text())

    def test_startup_and_shared_boundary(self):
        self.assertEqual(self.evaluate('messages'), [
            'Mus: HDMI-A-1', 'Fokus: ingen'])
        self.assertEqual(self.evaluate('outputAt({x:1535.9,y:100})'), 'HDMI-A-1')
        self.assertEqual(self.evaluate('outputAt({x:1536,y:100})'), 'HDMI-A-2')
        self.assertEqual(self.evaluate('outputAt({x:3456,y:100})'), 'unknown')

    def test_scaled_reversed_and_vertical_layouts(self):
        for screens, point, expected in [
            ("screen('HDMI-A-1',0,0,1280,720),screen('HDMI-A-2',1280,0,1536,864)", '{x:2048,y:432}', 'HDMI-A-2'),
            ("screen('HDMI-A-2',0,0,1920,1080),screen('HDMI-A-1',1920,0,1536,864)", '{x:960,y:540}', 'HDMI-A-2'),
            ("screen('HDMI-A-1',0,0,1536,864),screen('HDMI-A-2',0,864,1920,1080)", '{x:960,y:1404}', 'HDMI-A-2'),
        ]:
            with self.subTest(screens=screens):
                self.assertEqual(self.evaluate('workspace.screens=['+screens+']; outputAt('+point+')'), expected)

    def test_gaps_overlap_and_negative_coordinates(self):
        self.assertEqual(self.evaluate('outputAt({x:100,y:900})'), 'unknown')
        self.evaluate("workspace.screens.push(screen('overlap',1500,0,100,100))")
        self.assertEqual(self.evaluate('outputAt({x:1550,y:50})'), 'unknown')
        self.evaluate("workspace.screens=[screen('HDMI-A-2',-1920,0,1920,1080)]")
        self.assertEqual(self.evaluate('outputAt({x:-1,y:100})'), 'HDMI-A-2')

    def test_geometry_change_recomputes_stationary_cursor(self):
        self.evaluate('messages=[]; workspace.screens[0].geometry.x=4000; workspace.screens[0].geometryChanged.emit()')
        self.assertEqual(self.evaluate('messages'), ['Mus: unknown'])

    def test_hotplug_watches_new_geometry(self):
        self.evaluate("messages=[];workspace.screens=[screen('HDMI-A-2',0,0,1920,1080)];workspace.screensChanged.emit()")
        self.assertEqual(self.evaluate('messages'), ['Mus: HDMI-A-2'])
        self.evaluate('workspace.screens[0].geometry.x=2000;workspace.screens[0].geometryChanged.emit()')
        self.assertEqual(self.evaluate('messages[messages.length-1]'), 'Mus: unknown')

    def test_crossing_reports_both_outputs_and_same_display_motion_is_throttled(self):
        self.evaluate('messages=[];workspace.cursorPosChanged.emit()')
        self.assertEqual(self.evaluate('messages'), [])
        self.evaluate('workspace.cursorPos={x:1600,y:100};workspace.cursorPosChanged.emit();'
                      'workspace.cursorPos={x:1601,y:100};workspace.cursorPosChanged.emit()')
        self.assertEqual(self.evaluate('messages'), [
            'Mus: HDMI-A-2', 'Mouse-crossing: HDMI-A-1 -> HDMI-A-2 | cursor (100, 100) -> (1600, 100)'])
        self.evaluate('now+=1000;workspace.cursorPos={x:1602,y:100};workspace.cursorPosChanged.emit()')
        self.assertEqual(self.evaluate('messages[messages.length-1]'), 'Mouse-activity: HDMI-A-2')
        self.evaluate('workspace.cursorPos={x:1535,y:100};workspace.cursorPosChanged.emit()')
        self.assertEqual(self.evaluate('messages[messages.length-1]'),
                         'Mouse-crossing: HDMI-A-2 -> HDMI-A-1 | cursor (1602, 100) -> (1535, 100)')

    def test_geometry_remap_does_not_report_a_crossing_before_screen_signal(self):
        self.evaluate("messages=[];workspace.screens[0].geometry.x=4000;"
                      "workspace.screens[1].geometry.x=0;"
                      "workspace.cursorPosChanged.emit()")
        self.assertEqual(self.evaluate('messages'), ['Mus: HDMI-A-2'])

    def test_nondefault_output_and_unknown_geometry(self):
        self.evaluate("messages=[];workspace.screens=[screen('DP-1',0,0,1920,1080)];"
                      "workspace.screensChanged.emit();workspace.cursorPos={x:102,y:100};"
                      "workspace.cursorPosChanged.emit()")
        self.assertEqual(self.evaluate('messages'), ['Mus: DP-1', 'Mouse-activity: DP-1'])
        self.evaluate("messages=[];now+=1000;workspace.cursorPos={x:3000,y:100};"
                      "workspace.cursorPosChanged.emit()")
        self.assertEqual(self.evaluate('messages'), ['Mus: unknown'])
        self.evaluate("messages=[];workspace.cursorPos={x:100,y:100};workspace.cursorPosChanged.emit()")
        self.assertEqual(self.evaluate('messages'), ['Mus: DP-1', 'Mouse-activity: DP-1'])


class AppWindowBridgeTests(unittest.TestCase):
    def test_desktop_snapshot_includes_app_identity_display_and_size(self):
        engine = QJSEngine()
        setup = engine.evaluate('''
            var messages = [];
            function signal() { return {connect: function() {}}; }
            function QTimer() { this.timeout = signal(); this.start = function() {}; }
            function print() {}
            function callDBus(a,b,c,d,message) { messages.push(message); }
            var workspace = {
                windowList: function() { return [{
                    pid: 123, caption: "Player", desktopFileName: "player",
                    resourceClass: "Player", output: {name: "DP-1"},
                    clientGeometry: {width: 640, height: 360}
                }]; },
                activeWindow: null, windowActivated: signal()
            };
        ''')
        self.assertFalse(setup.isError(), setup.toString())
        source = SOURCE.with_name('firefox.js').read_text()
        result = engine.evaluate(source)
        self.assertFalse(result.isError(), result.toString())
        messages = engine.evaluate('messages').toVariant()
        snapshot = json.loads(messages[0].removeprefix('Desktop-snapshot: '))
        self.assertEqual(snapshot, [{
            'pid': 123, 'title': 'Player', 'desktop': 'player',
            'class': 'Player', 'output': 'DP-1', 'size': [640, 360],
        }])


if __name__ == '__main__':
    unittest.main()
