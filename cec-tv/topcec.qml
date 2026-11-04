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

    component SelectableLabel: Controls.TextArea {
        readOnly: true
        selectByMouse: true
        textFormat: TextEdit.PlainText
        padding: 0
        background: null
        color: Kirigami.Theme.textColor
        wrapMode: TextEdit.Wrap
    }

    component SelectableHeading: SelectableLabel {
        property int level: 2
        font: headingStyle.font
        Kirigami.Heading {
            id: headingStyle
            visible: false
            level: parent.level
        }
    }

    function showCaption(text) {
        captionMenu.caption = text
        captionMenu.popup()
    }

    function displayedText(item) {
        if (!item.visible)
            return ""
        if (typeof item.text === "string" && item.text.length)
            return item.text
        let parts = []
        for (let child of item.children) {
            let text = displayedText(child)
            if (text.length)
                parts.push(text)
        }
        return parts.join("\n")
    }

    Controls.Menu {
        id: captionMenu
        objectName: "captionCopyMenu"
        property string caption: ""
        Controls.MenuItem {
            objectName: "copyCaptionAction"
            text: "Copy text"
            onTriggered: topcec.copyText(captionMenu.caption)
        }
    }

    component CopyableButton: Controls.Button {
        TapHandler {
            acceptedButtons: Qt.RightButton
            onTapped: root.showCaption(parent.text)
        }
        Keys.onMenuPressed: root.showCaption(text)
    }

    component CopyableCheckBox: Controls.CheckBox {
        TapHandler {
            acceptedButtons: Qt.RightButton
            onTapped: root.showCaption(parent.text)
        }
        Keys.onMenuPressed: root.showCaption(text)
    }

    component CopyableComboBox: Controls.ComboBox {
        TapHandler {
            acceptedButtons: Qt.RightButton
            onTapped: root.showCaption(parent.editable ? parent.editText : parent.currentText)
        }
        Keys.onMenuPressed: root.showCaption(editable ? editText : currentText)
    }

    component CopyableSpinBox: Controls.SpinBox {
        TapHandler {
            acceptedButtons: Qt.RightButton
            onTapped: root.showCaption(parent.textFromValue(parent.value, parent.locale))
        }
        Keys.onMenuPressed: root.showCaption(textFromValue(value, locale))
    }

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
        actions: [
            Kirigami.Action {
                objectName: "copyPageAction"
                text: "Copy page text"
                icon.name: "edit-copy"
                onTriggered: topcec.copyText(root.title + "\n" + root.displayedText(pageContent))
            }
        ]

        ColumnLayout {
            id: pageContent
            objectName: "pageContent"
            width: parent.width
            spacing: Kirigami.Units.largeSpacing

            StackLayout {
                Layout.fillWidth: true
                currentIndex: topcec.dbusOnly && !topcec.backendAvailable ? 0 : 1

                ColumnLayout {
                    width: parent.width
                    spacing: Kirigami.Units.largeSpacing

                    SelectableHeading {
                        objectName: "setupHeading"
                        level: 2
                        text: "topCEC Backend Not Available"
                    }
                    SelectableLabel {
                        objectName: "setupExplanation"
                        Layout.fillWidth: true
                        wrapMode: Text.Wrap
                        text: "The topCEC background service is required to monitor displays and control HDMI-CEC devices. It runs outside the Flatpak sandbox."
                    }
                    SelectableLabel {
                        Layout.fillWidth: true
                        wrapMode: Text.Wrap
                        font.bold: true
                        text: topcec.connectionMessage
                    }
                    SelectableLabel {
                        Layout.fillWidth: true
                        wrapMode: Text.Wrap
                        text: "To install the host service, open a terminal and clone the official repository. Then enter the topCEC repository root before running the installer."
                    }
                    SelectableLabel {
                        Layout.fillWidth: true
                        wrapMode: Text.Wrap
                        text: "1. Clone the repository and enter it:"
                    }
                    Controls.TextArea {
                        objectName: "setupCommands"
                        Layout.fillWidth: true
                        Layout.preferredHeight: 58
                        readOnly: true
                        selectByMouse: true
                        wrapMode: TextEdit.NoWrap
                        text: "git clone https://github.com/Arthur-D/topCEC.git\ncd topCEC"
                    }
                    SelectableLabel {
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
                    SelectableLabel {
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
                    SelectableLabel {
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
                    SelectableLabel {
                        Layout.fillWidth: true
                        wrapMode: Text.Wrap
                        text: "5. Return here. The GUI reconnects when the service appears; you can also retry now."
                    }
                    RowLayout {
                        CopyableButton {
                            objectName: "retryConnectionButton"
                            text: "Retry Connection"
                            enabled: topcec.connectionState !== "connecting"
                            onClicked: topcec.retryConnection()
                        }
                        CopyableButton {
                            objectName: "repositoryButton"
                            text: "Open topCEC repository"
                            onClicked: Qt.openUrlExternally("https://github.com/Arthur-D/topCEC")
                        }
                    }
                    SelectableHeading {
                        level: 3
                        text: "Diagnostics"
                    }
                    Controls.TextArea {
                        objectName: "setupDiagnostics"
                        Layout.fillWidth: true
                        Layout.preferredHeight: 78
                        readOnly: true
                        selectByMouse: true
                        text: topcec.diagnostics
                    }
                }

                ColumnLayout {
                    width: parent.width
                    spacing: Kirigami.Units.largeSpacing

                    SelectableHeading {
                        level: 2
                        text: "TV power control"
                    }

                    SelectableLabel {
                        text: "Service: " + topcec.serviceStatus
                        font.bold: true
                    }
                    SelectableLabel {
                        Layout.fillWidth: true
                        wrapMode: Text.Wrap
                        text: topcec.connectionMessage
                    }
                    CopyableButton {
                        text: "Retry Connection"
                        visible: !topcec.backendAvailable
                        enabled: topcec.connectionState !== "connecting"
                        onClicked: topcec.retryConnection()
                    }
                    SelectableLabel {
                        text: "TV power: " + topcec.powerState
                    }
                    SelectableLabel {
                        Layout.fillWidth: true
                        wrapMode: Text.Wrap
                        text: topcec.standbyReason
                    }

                    RowLayout {
                        CopyableButton {
                            text: "TV on"
                            enabled: topcec.simulationMode
                                     || (topcec.backendAvailable
                                         && topcec.serviceStatus === "running")
                            onClicked: topcec.requestPower("on")
                        }
                        CopyableButton {
                            text: "TV standby"
                            enabled: topcec.simulationMode
                                     || (topcec.backendAvailable
                                         && topcec.serviceStatus === "running"
                                         && topcec.standbyReason === "Automatic standby allowed")
                            onClicked: topcec.requestPower("off")
                        }
                    }

                    CopyableCheckBox {
                        text: "Simulate manual actions"
                        checked: topcec.simulationMode
                        onToggled: topcec.setSimulationMode(checked)
                    }
                    SelectableLabel {
                        Layout.fillWidth: true
                        wrapMode: Text.Wrap
                        text: topcec.actionMessage
                    }

                    Kirigami.Separator {
                        Layout.fillWidth: true
                    }

                    SelectableHeading {
                        level: 3
                        text: "Configuration"
                    }

                    SelectableLabel { text: "TV display (KWin output name)" }
                    CopyableComboBox {
                        id: outputField
                        objectName: "outputField"
                        Layout.fillWidth: true
                        editable: true
                        onEditTextChanged: {
                            if (activeFocus) root.settingsDirty = true
                        }
                        onActivated: root.settingsDirty = true
                    }

                    SelectableLabel { text: "CEC adapter" }
                    CopyableComboBox {
                        id: adapterField
                        objectName: "adapterField"
                        Layout.fillWidth: true
                        editable: true
                        onEditTextChanged: {
                            if (activeFocus) root.settingsDirty = true
                        }
                        onActivated: root.settingsDirty = true
                    }

                    SelectableLabel { text: "Inactivity timeout" }
                    CopyableComboBox {
                        id: timeoutMode
                        Layout.fillWidth: true
                        model: ["KDE-managed", "Custom (minutes)", "Disabled"]
                        onActivated: root.settingsDirty = true
                    }
                    CopyableSpinBox {
                        id: timeoutMinutes
                        from: 1
                        to: 1440
                        onValueModified: root.settingsDirty = true
                        enabled: timeoutMode.currentIndex === 1
                    }

                    SelectableLabel { text: "Input devices (one path per line)" }
                    Controls.TextArea {
                        id: devicesField
                        objectName: "devicesField"
                        Layout.fillWidth: true
                        Layout.preferredHeight: 72
                        selectByMouse: true
                        onTextChanged: {
                            if (activeFocus) root.settingsDirty = true
                        }
                        wrapMode: TextEdit.NoWrap
                    }

                    SelectableLabel { text: "Firefox mute-tab labels (one per line)" }
                    Controls.TextArea {
                        id: labelsField
                        Layout.fillWidth: true
                        Layout.preferredHeight: 56
                        selectByMouse: true
                        onTextChanged: {
                            if (activeFocus) root.settingsDirty = true
                        }
                    }

                    SelectableLabel { text: "Axis deadzone (%)" }
                    CopyableSpinBox {
                        id: deadzoneField
                        from: 1
                        to: 25
                        onValueModified: root.settingsDirty = true
                    }
                    SelectableLabel { text: "ABS_RZ deadzone (%)" }
                    CopyableSpinBox {
                        id: rzDeadzoneField
                        from: 1
                        to: 25
                        onValueModified: root.settingsDirty = true
                    }

                    CopyableButton {
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

                    SelectableHeading {
                        level: 3
                        text: "Diagnostics"
                    }
                    Controls.TextArea {
                        objectName: "backendDiagnostics"
                        Layout.fillWidth: true
                        Layout.preferredHeight: 110
                        readOnly: true
                        selectByMouse: true
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
