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
    property string submittedSettings: ""

    function settingsValues() {
        return {
            targetOutput: outputField.editText,
            adapter: adapterField.editText,
            timeoutMode: timeoutMode.currentIndex === 0 ? "kde"
                : (timeoutMode.currentIndex === 1 ? "custom" : "never"),
            timeoutMinutes: timeoutMinutes.value,
            devices: devicesField.text,
            muteLabels: labelsField.text,
            axisDeadzone: deadzoneField.value,
            rzDeadzone: rzDeadzoneField.value
        }
    }

    function equipmentChoices(options, values) {
        let choices = []
        for (let item of options) {
            let configured = values.filter(value => value === item.path || (item.aliases || []).includes(value))
            for (let path of configured.length ? configured : [item.path])
                choices.push({path: path, label: path === item.path ? item.label : item.label + " (configured as " + path + ")", available: true})
        }
        return choices
    }

    function inputDetected(path) {
        return topcec.detectedInputs.some(item => item.path === path || (item.aliases || []).includes(path))
    }

    function unresolvedInputs() {
        return inputPaths().filter(path => !inputDetected(path))
    }

    function retainedValue(value) {
        return value + (topcec.equipmentAvailabilityKnown
            ? " (unavailable / not detected)" : " (availability unknown)")
    }

    readonly property bool equipmentReady: outputField.acceptable && adapterField.acceptable
        && inputPaths().length > 0 && (manualInputs.checked || unresolvedInputs().length === 0)

    function inputPaths() {
        return devicesField.text.split("\n").map(path => path.trim()).filter(path => path.length)
    }

    function selectedInputLabels() {
        return inputPaths().map(path => {
            let item = topcec.detectedInputs.find(device => device.path === path || (device.aliases || []).includes(path))
            return item ? item.label : root.retainedValue(path)
        })
    }

    function savedInputPaths() {
        let paths = inputPaths().map(path => {
            let item = topcec.detectedInputs.find(device => device.path === path || (device.aliases || []).includes(path))
            return item ? item.path : path
        })
        return [...new Set(paths)].join("\n")
    }

    function setInputDeviceSelected(device, selected) {
        let paths = inputPaths().filter(path => path !== device.path && !(device.aliases || []).includes(path))
        if (selected)
            paths.push(device.path)
        devicesField.text = paths.join("\n")
        settingsDirty = true
    }

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

    component EquipmentSelector: CopyableComboBox {
        property var equipment: []
        property bool availabilityKnown: topcec.equipmentAvailabilityKnown
        property bool syncing: false
        property bool manualEntry: false
        property string prompt: "Choose a detected device"
        readonly property bool detected: equipment.some(item => item.path === editText)
        readonly property bool acceptable: editText.trim().length > 0 && (manualEntry || detected)
        editable: manualEntry
        displayText: currentIndex < 0 ? prompt : currentText
        textRole: "label"
        function synchronize(value) {
            syncing = true
            model = root.equipmentChoices(equipment, [value])
            currentIndex = model.findIndex(item => item.path === value)
            editText = value
            syncing = false
        }
        onEquipmentChanged: synchronize(editText)
        onAvailabilityKnownChanged: synchronize(editText)
        onManualEntryChanged: synchronize(editText)
        onActivated: {
            editText = model[index].path
            root.settingsDirty = true
        }
        onEditTextChanged: {
            if (!syncing && activeFocus)
                root.settingsDirty = true
        }
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
        outputField.synchronize(topcec.configurationSource === "defaults" ? "" : topcec.setting("target_output"))
        adapterField.synchronize(topcec.configurationSource === "defaults" ? "" : topcec.setting("cec_port"))
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
            if (root.submittedSettings && JSON.stringify(root.settingsValues()) !== root.submittedSettings)
                return
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

            ColumnLayout {
                Layout.fillWidth: true
                visible: topcec.equipmentRecoveryCommands.length > 0
                SelectableLabel {
                    Layout.fillWidth: true
                    text: topcec.compatibilityMessage
                }
                SelectableLabel {
                    objectName: "hostUpdateInstructions"
                    Layout.fillWidth: true
                    text: "Run this command in a host terminal from any directory. When prompted, paste the full absolute path to your existing official topCEC checkout on main, without quotes (spaces are supported). It verifies that checkout and stops on update or install failure. Your settings are preserved; the service restarts after installation."
                }
                Controls.TextArea {
                    objectName: "equipmentRecoveryCommands"
                    Layout.fillWidth: true
                    readOnly: true
                    selectByMouse: true
                    wrapMode: TextEdit.WrapAnywhere
                    text: topcec.equipmentRecoveryCommands
                }
                CopyableButton {
                    objectName: "copyEquipmentRecoveryCommands"
                    text: "Copy host update command"
                    onClicked: topcec.copyText(topcec.equipmentRecoveryCommands)
                }
            }

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

                    ColumnLayout {
                        objectName: "inputPermissionHelp"
                        Layout.fillWidth: true
                        visible: topcec.inputPermissionMessage.length > 0
                        spacing: Kirigami.Units.smallSpacing

                        SelectableHeading {
                            level: 3
                            text: "Input device access"
                        }
                        SelectableLabel {
                            Layout.fillWidth: true
                            text: topcec.inputPermissionMessage
                        }
                        Controls.TextArea {
                            objectName: "inputPermissionCommand"
                            Layout.fillWidth: true
                            visible: topcec.inputPermissionCommand.length > 0
                            text: topcec.inputPermissionCommand
                            readOnly: true
                            selectByMouse: true
                            wrapMode: TextEdit.Wrap
                        }
                        CopyableButton {
                            objectName: "copyInputPermissionCommand"
                            visible: topcec.inputPermissionCommand.length > 0
                            text: "Copy input-group command"
                            onClicked: topcec.copyText(topcec.inputPermissionCommand)
                        }
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
                    SelectableLabel {
                        Layout.fillWidth: true
                        text: "Choose detected equipment below. Undetected saved values and drafts are retained in notices, not selected as available hardware. Nothing is selected automatically."
                    }
                    SelectableLabel {
                        Layout.fillWidth: true
                        text: topcec.equipmentMessage
                    }
                    SelectableLabel {
                        Layout.fillWidth: true
                        visible: topcec.configurationSource === "defaults"
                        text: "No saved host configuration. Legacy hardware defaults are not selected; choose the devices you want to monitor, then save."
                    }

                    SelectableLabel { text: "TV display (KWin output name)" }
                    EquipmentSelector {
                        id: outputField
                        objectName: "outputField"
                        Layout.fillWidth: true
                        equipment: topcec.detectedOutputs
                        manualEntry: manualOutput.checked
                        prompt: "Choose a detected display"
                    }
                    SelectableLabel {
                        objectName: "retainedOutput"
                        Layout.fillWidth: true
                        visible: !outputField.detected && outputField.editText.length > 0
                        text: "Retained display value: " + root.retainedValue(outputField.editText)
                    }
                    CopyableCheckBox {
                        id: manualOutput
                        objectName: "manualOutput"
                        text: "Use a manually entered display name"
                        onToggled: root.settingsDirty = true
                    }

                    SelectableLabel { text: "CEC adapter" }
                    EquipmentSelector {
                        id: adapterField
                        objectName: "adapterField"
                        Layout.fillWidth: true
                        equipment: topcec.detectedAdapters
                        manualEntry: manualAdapter.checked
                        prompt: "Choose a detected CEC adapter"
                    }
                    SelectableLabel {
                        objectName: "retainedAdapter"
                        Layout.fillWidth: true
                        visible: !adapterField.detected && adapterField.editText.length > 0
                        text: "Retained adapter value: " + root.retainedValue(adapterField.editText)
                    }
                    CopyableCheckBox {
                        id: manualAdapter
                        objectName: "manualAdapter"
                        text: "Use a manually entered adapter path"
                        onToggled: root.settingsDirty = true
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

                    SelectableLabel { text: "Input devices" }
                    SelectableLabel {
                        objectName: "selectedInputSummary"
                        Layout.fillWidth: true
                        text: root.inputPaths().length + " selected"
                            + (root.unresolvedInputs().length ? " (" + root.unresolvedInputs().length + " unlisted)" : "")
                            + (root.inputPaths().length ? ":\n" + root.selectedInputLabels().slice(0, 3).join("\n") : ". Choose devices to monitor.")
                            + (root.inputPaths().length > 3 ? "\nAnd " + (root.inputPaths().length - 3) + " more." : "")
                    }
                    RowLayout {
                        CopyableButton {
                            id: inputChooserToggle
                            objectName: "inputChooserToggle"
                            checkable: true
                            text: checked ? "Hide input devices"
                                : "Choose input devices (" + topcec.detectedInputs.length + " detected)"
                            Accessible.description: checked ? "Input device checklist expanded" : "Input device checklist collapsed"
                        }
                        CopyableButton {
                            objectName: "copySelectedInputs"
                            text: "Copy selected paths"
                            enabled: root.inputPaths().length > 0
                            onClicked: topcec.copyText(root.inputPaths().join("\n"))
                        }
                    }
                    Controls.ScrollView {
                        id: inputChooserScroll
                        objectName: "inputChooserScroll"
                        Layout.fillWidth: true
                        Layout.preferredHeight: Math.min(inputChoiceList.implicitHeight, Kirigami.Units.gridUnit * 10)
                        Layout.minimumHeight: 0
                        Layout.maximumHeight: Layout.preferredHeight
                        visible: inputChooserToggle.checked
                        clip: true
                        contentWidth: availableWidth
                        Controls.ScrollBar.horizontal.policy: Controls.ScrollBar.AlwaysOff
                        Controls.ScrollBar.vertical.policy: contentHeight > availableHeight
                            ? Controls.ScrollBar.AlwaysOn : Controls.ScrollBar.AlwaysOff
                        Flickable {
                            id: inputFlickable
                            contentWidth: width
                            contentHeight: inputChoiceList.height
                            boundsBehavior: Flickable.StopAtBounds
                            ColumnLayout {
                                id: inputChoiceList
                                width: inputFlickable.width
                                Repeater {
                                    id: inputChoices
                                    objectName: "inputChoices"
                                    model: topcec.detectedInputs
                                    delegate: CopyableCheckBox {
                                        required property var modelData
                                        objectName: "inputChoice:" + modelData.path
                                        Layout.fillWidth: true
                                        text: modelData.label
                                        checked: root.inputPaths().some(path => path === modelData.path || (modelData.aliases || []).includes(path))
                                        onToggled: root.setInputDeviceSelected(modelData, checked)
                                        onActiveFocusChanged: {
                                            if (activeFocus) {
                                                let top = y
                                                if (top < inputFlickable.contentY)
                                                    inputFlickable.contentY = top
                                                else if (top + height > inputFlickable.contentY + inputFlickable.height)
                                                    inputFlickable.contentY = top + height - inputFlickable.height
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                    SelectableLabel {
                        Layout.fillWidth: true
                        text: "Select detected devices to monitor, then save below. Detected selections are saved using stable paths when available. Detection does not guarantee read access."
                    }
                    SelectableLabel {
                        objectName: "retainedInputs"
                        Layout.fillWidth: true
                        visible: root.unresolvedInputs().length > 0
                        text: "Retained input values (not selected as detected devices):\n"
                            + root.unresolvedInputs().map(path => root.retainedValue(path)).join("\n")
                    }
                    CopyableButton {
                        objectName: "removeUndetectedInputs"
                        text: "Remove unlisted input values"
                        visible: root.unresolvedInputs().length > 0
                        onClicked: {
                            devicesField.text = root.inputPaths().filter(path => root.inputDetected(path)).join("\n")
                            root.settingsDirty = true
                        }
                    }
                    CopyableCheckBox {
                        id: manualInputs
                        objectName: "manualInputs"
                        text: "Use manually entered input paths"
                        onToggled: root.settingsDirty = true
                    }
                    Controls.TextArea {
                        id: devicesField
                        objectName: "devicesField"
                        Layout.fillWidth: true
                        Layout.preferredHeight: 72
                        visible: manualInputs.checked
                        Accessible.name: "Input device paths (one per line)"
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

                    SelectableLabel {
                        objectName: "equipmentSaveGuidance"
                        Layout.fillWidth: true
                        visible: !root.equipmentReady
                        text: "Before saving, choose a detected display, adapter and at least one input. Remove unlisted input values or deliberately enable manual entry to keep them. Existing settings are not changed until you save."
                    }
                    CopyableButton {
                        objectName: "saveSettingsButton"
                        text: "Save settings and restart service"
                        Layout.fillWidth: true
                        enabled: topcec.settingsEnabled && root.equipmentReady
                        onClicked: {
                            if (!root.equipmentReady)
                                return
                            let values = root.settingsValues()
                            root.submittedSettings = JSON.stringify(values)
                            values.devices = root.savedInputPaths()
                            topcec.applySettings(values)
                        }
                    }
                    SelectableLabel {
                        objectName: "settingsSaveStatus"
                        Layout.fillWidth: true
                        text: root.settingsDirty
                            ? "Unsaved changes. Save settings and restart service to keep these selections across restarts."
                            : "No unsaved changes."
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
