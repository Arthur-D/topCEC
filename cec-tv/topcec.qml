// SPDX-License-Identifier: GPL-3.0-or-later
import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Kirigami.ApplicationWindow {
    id: root
    title: "topCEC"
    minimumWidth: 620
    minimumHeight: 680

    pageStack.initialPage: Kirigami.ScrollablePage {
        title: "topCEC"

        ColumnLayout {
            width: parent.width
            spacing: Kirigami.Units.largeSpacing

            Kirigami.Heading {
                level: 2
                text: "TV power control"
            }

            Controls.Label {
                text: "Service: " + topcec.serviceStatus
                font.bold: true
            }
            Controls.Label {
                text: "TV power: " + topcec.powerState
            }
            Controls.Label {
                Layout.fillWidth: true
                wrapMode: Text.Wrap
                text: topcec.standbyReason
            }

            RowLayout {
                Controls.Button {
                    text: "TV on"
                    enabled: topcec.simulationMode || topcec.serviceStatus === "running"
                    onClicked: topcec.requestPower("on")
                }
                Controls.Button {
                    text: "TV standby"
                    enabled: topcec.simulationMode
                             || (topcec.serviceStatus === "running"
                                 && topcec.standbyReason === "Automatic standby allowed")
                    onClicked: topcec.requestPower("off")
                }
            }

            Controls.CheckBox {
                text: "Simulate manual actions"
                checked: topcec.simulationMode
                onToggled: topcec.setSimulationMode(checked)
            }
            Controls.Label {
                Layout.fillWidth: true
                wrapMode: Text.Wrap
                text: topcec.actionMessage
            }

            Kirigami.Separator {
                Layout.fillWidth: true
            }

            Kirigami.Heading {
                level: 3
                text: "Configuration"
            }

            Controls.Label { text: "TV display (KWin output name)" }
            Controls.ComboBox {
                id: outputField
                Layout.fillWidth: true
                editable: true
                model: topcec.outputOptions
                Component.onCompleted: editText = topcec.setting("target_output")
            }

            Controls.Label { text: "CEC adapter" }
            Controls.ComboBox {
                id: adapterField
                Layout.fillWidth: true
                editable: true
                model: topcec.adapterOptions
                Component.onCompleted: editText = topcec.setting("cec_port")
            }

            Controls.Label { text: "Inactivity timeout" }
            Controls.ComboBox {
                id: timeoutMode
                Layout.fillWidth: true
                model: ["KDE-managed", "Custom (minutes)", "Disabled"]
                currentIndex: topcec.usesKdeTimeout() ? 0
                    : (topcec.setting("timeout_seconds") === null ? 2 : 1)
            }
            Controls.SpinBox {
                id: timeoutMinutes
                from: 1
                to: 1440
                value: topcec.timeoutMinutes()
                enabled: timeoutMode.currentIndex === 1
            }

            Controls.Label { text: "Input devices (one path per line)" }
            Controls.TextArea {
                id: devicesField
                Layout.fillWidth: true
                Layout.preferredHeight: 72
                text: topcec.deviceList()
                wrapMode: TextEdit.NoWrap
            }

            Controls.Label { text: "Firefox mute-tab labels (one per line)" }
            Controls.TextArea {
                id: labelsField
                Layout.fillWidth: true
                Layout.preferredHeight: 56
                text: topcec.muteLabelList()
            }

            Controls.Label { text: "Axis deadzone (%)" }
            Controls.SpinBox {
                id: deadzoneField
                from: 1
                to: 25
                value: Math.round(topcec.setting("axis_deadzone_percent"))
            }
            Controls.Label { text: "ABS_RZ deadzone (%)" }
            Controls.SpinBox {
                id: rzDeadzoneField
                from: 1
                to: 25
                value: Math.round(topcec.setting("rz_deadzone_percent"))
            }

            Controls.Button {
                text: "Save settings and restart service"
                Layout.fillWidth: true
                enabled: topcec.settingsEnabled
                onClicked: topcec.applySettings({
                    targetOutput: outputField.editText,
                    adapter: adapterField.editText,
                    timeoutMode: timeoutMode.currentIndex === 0 ? "kde"
                        : (timeoutMode.currentIndex === 1 ? "custom" : "never"),
                    timeoutMinutes: timeoutMinutes.value,
                    devices: devicesField.text,
                    muteLabels: labelsField.text,
                    axisDeadzone: deadzoneField.value,
                    rzDeadzone: rzDeadzoneField.value
                })
            }

            Kirigami.Heading {
                level: 3
                text: "Diagnostics"
            }
            Controls.TextArea {
                Layout.fillWidth: true
                Layout.preferredHeight: 110
                readOnly: true
                text: topcec.diagnostics
            }
        }
    }

    Timer {
        interval: 2000
        running: true
        repeat: true
        onTriggered: topcec.refresh()
    }
}
