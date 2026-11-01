"""Hardware-free KWin JavaScript tests; requires PySide6 (QtQml)."""
# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path
import unittest
from PySide6.QtCore import QCoreApplication
from PySide6.QtQml import QJSEngine

APP = QCoreApplication.instance() or QCoreApplication([])
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
            'Mus: HDMI-A-1', 'Mouse-activity: HDMI-A-1', 'Fokus: ingen'])
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

    def test_mouse_activity_is_throttled_and_reports_actual_output(self):
        self.evaluate('messages=[];workspace.cursorPosChanged.emit()')
        self.assertEqual(self.evaluate('messages'), [])
        self.evaluate('workspace.cursorPos={x:1600,y:100};workspace.cursorPosChanged.emit();workspace.cursorPosChanged.emit()')
        self.assertEqual(self.evaluate('messages'), [
            'Mus: HDMI-A-2', 'Mouse-activity: HDMI-A-2'])
        self.evaluate('now+=1000;workspace.cursorPosChanged.emit()')
        self.assertEqual(self.evaluate('messages.filter(m=>m==="Mouse-activity: HDMI-A-2").length'), 2)

    def test_nondefault_output_and_unknown_geometry(self):
        self.evaluate("messages=[];workspace.screens=[screen('DP-1',0,0,1920,1080)];"
                      "workspace.screensChanged.emit();workspace.cursorPosChanged.emit()")
        self.assertIn('Mouse-activity: DP-1', self.evaluate('messages'))
        self.evaluate("messages=[];now+=1000;workspace.cursorPos={x:3000,y:100};"
                      "workspace.cursorPosChanged.emit()")
        self.assertEqual(self.evaluate('messages'), ['Mus: unknown'])


if __name__ == '__main__':
    unittest.main()
