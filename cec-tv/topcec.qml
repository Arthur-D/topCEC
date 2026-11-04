// SPDX-License-Identifier: GPL-3.0-or-later
import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Kirigami.ApplicationWindow {
    id: root
    title: topcec.dbusOnly && !topcec.backendAvailable
        ? "topCEC Backend Not Available" : "topCEC"
    minimumWidth: 620
    minimumHeight: 680
    property bool settingsDirty: false

    function loadSettings() {
        if (settingsDirty)
            return
        outputField.model = topcec.outputOptions
        outputField.editText = topcec.setting("target_output")
        adapterField.model = topcec.adapterOptions
        adapterField.editText = topcec.setting("cec_port")
        timeoutMode.currentIndex = topcec.usesKdeTimeout() ? 0
            : (topcec.setting("timeout_seconds") === null ? 2 : 1)
        timeoutMinutes.value = topcec.timeoutMinutes()
        devicesField.text = topcec.deviceList()
        labelsField.text = topcec.muteLabelList()
        deadzoneField.value = Math.round(topcec.setting("axis_deadzone_percent"))
        rzDeadzoneField.value = Math.round(topcec.setting("rz_deadzone_percent"))
    }

    Component.onCompleted: loadSettings()
    Connections {
        target: topcec
        function onConfigurationChanged() { root.loadSettings() }
        function onSettingsSaved() {
            root.settingsDirty = false
            root.loadSettings()
        }
    }

    pageStack.initialPage: Kirigami.ScrollablePage {
        title: "topCEC"

        ColumnLayout {
            width: parent.width
            spacing: Kirigami.Units.largeSpacing

            StackLayout {
                Layout.fillWidth: true
                currentIndex: topcec.dbusOnly && !topcec.backendAvailable ? 0 : 1

                ColumnLayout {
                    width: parent.width
                    spacing: Kirigami.Units.largeSpacing

                    Kirigami.Heading {
                        level: 2
                        text: "topCEC Backend Not Available"
                    }
                    Controls.Label {
                        Layout.fillWidth: true
                        wrapMode: Text.Wrap
                        text: "The topCEC background service is required to monitor displays and control HDMI-CEC devices. It runs outside the Flatpak sandbox."
                    }
                    Controls.Label {
                        Layout.fillWidth: true
                        wrapMode: Text.Wrap
                        font.bold: true
                        text: topcec.connectionMessage
                    }
                    Controls.Label {
                        Layout.fillWidth: true
                        wrapMode: Text.Wrap
                        text: "To install the host service, open a terminal and clone the official repository. Then enter the topCEC repository root before running the installer."
                    }
                    Controls.Label {
                        Layout.fillWidth: true
                        wrapMode: Text.Wrap
                        text: "1. Clone the repository and enter it:"
                    }
                    Controls.TextArea {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 58
                        readOnly: true
                        selectByMouse: true
                        wrapMode: TextEdit.NoWrap
                        text: "git clone https://github.com/Arthur-D/topCEC.git\ncd topCEC"
                    }
                    Controls.Label {
                        Layout.fillWidth: true
                        wrapMode: Text.Wrap
                        text: "2. From the repository root, install the host service and GUI:"
                    }
                    Controls.TextArea {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 34
                        readOnly: true
                        selectByMouse: true
                        wrapMode: TextEdit.NoWrap
                        text: "bash packaging/install-user.sh"
                    }
                    Controls.Label {
                        Layout.fillWidth: true
                        wrapMode: Text.Wrap
                        text: "3. Before first start, configure the correct display, CEC adapter, and input devices with the native host GUI. Once the service is started, you can configure it here even if input initialization fails:"
                    }
                    Controls.TextArea {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 34
                        readOnly: true
                        selectByMouse: true
                        wrapMode: TextEdit.NoWrap
                        text: "~/.local/bin/topcec-gui"
                    }
                    Controls.Label {
                        Layout.fillWidth: true
                        wrapMode: Text.Wrap
                        text: "4. Enable and start the user service:"
                    }
                    Controls.TextArea {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 34
                        readOnly: true
                        selectByMouse: true
                        wrapMode: TextEdit.NoWrap
                        text: "systemctl --user enable --now topcec.service"
                    }
                    Controls.Label {
                        Layout.fillWidth: true
                        wrapMode: Text.Wrap
                        text: "5. Return here. The GUI reconnects when the service appears; you can also retry now."
                    }
                    RowLayout {
                        Controls.Button {
                            text: "Retry Connection"
                            enabled: topcec.connectionState !== "connecting"
                            onClicked: topcec.retryConnection()
                        }
                        Controls.Button {
                            text: "Open topCEC repository"
                            onClicked: Qt.openUrlExternally("https://github.com/Arthur-D/topCEC")
                        }
                    }
                    Kirigami.Heading {
                        level: 3
                        text: "Diagnostics"
                    }
                    Controls.TextArea {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 78
                        readOnly: true
                        text: topcec.diagnostics
                    }
                }

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
                        Layout.fillWidth: true
                        wrapMode: Text.Wrap
                        text: topcec.connectionMessage
                    }
                    Controls.Button {
                        text: "Retry Connection"
                        visible: !topcec.backendAvailable
                        enabled: topcec.connectionState !== "connecting"
                        onClicked: topcec.retryConnection()
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
                            enabled: topcec.simulationMode
                                     || (topcec.backendAvailable
                                         && topcec.serviceStatus === "running")
                            onClicked: topcec.requestPower("on")
                        }
                        Controls.Button {
                            text: "TV standby"
                            enabled: topcec.simulationMode
                                     || (topcec.backendAvailable
                                         && topcec.serviceStatus === "running"
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
                        objectName: "outputField"
                        Layout.fillWidth: true
                        editable: true
                        onEditTextChanged: {
                            if (activeFocus) root.settingsDirty = true
                        }
                        onActivated: root.settingsDirty = true
                    }

                    Controls.Label { text: "CEC adapter" }
                    Controls.ComboBox {
                        id: adapterField
                        objectName: "adapterField"
                        Layout.fillWidth: true
                        editable: true
                        onEditTextChanged: {
                            if (activeFocus) root.settingsDirty = true
                        }
                        onActivated: root.settingsDirty = true
                    }

                    Controls.Label { text: "Inactivity timeout" }
                    Controls.ComboBox {
                        id: timeoutMode
                        Layout.fillWidth: true
                        model: ["KDE-managed", "Custom (minutes)", "Disabled"]
                        onActivated: root.settingsDirty = true
                    }
                    Controls.SpinBox {
                        id: timeoutMinutes
                        from: 1
                        to: 1440
                        onValueModified: root.settingsDirty = true
                        enabled: timeoutMode.currentIndex === 1
                    }

                    Controls.Label { text: "Input devices (one path per line)" }
                    Controls.TextArea {
                        id: devicesField
                        objectName: "devicesField"
                        Layout.fillWidth: true
                        Layout.preferredHeight: 72
                        onTextChanged: {
                            if (activeFocus) root.settingsDirty = true
                        }
                        wrapMode: TextEdit.NoWrap
                    }

                    Controls.Label { text: "Firefox mute-tab labels (one per line)" }
                    Controls.TextArea {
                        id: labelsField
                        Layout.fillWidth: true
                        Layout.preferredHeight: 56
                        onTextChanged: {
                            if (activeFocus) root.settingsDirty = true
                        }
                    }

                    Controls.Label { text: "Axis deadzone (%)" }
                    Controls.SpinBox {
                        id: deadzoneField
                        from: 1
                        to: 25
                        onValueModified: root.settingsDirty = true
                    }
                    Controls.Label { text: "ABS_RZ deadzone (%)" }
                    Controls.SpinBox {
                        id: rzDeadzoneField
                        from: 1
                        to: 25
                        onValueModified: root.settingsDirty = true
                    }

                    Controls.Button {
                        objectName: "saveSettingsButton"
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
        }
    }

    Timer {
        interval: topcec.backendAvailable ? 5000 : 30000
        running: true
        repeat: true
        onTriggered: topcec.refresh()
    }
}
