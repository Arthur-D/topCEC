// SPDX-License-Identifier: GPL-3.0-or-later
import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.kirigamiaddons.formcard as FormCard

Kirigami.ApplicationWindow {
    id: root
    title: topcec.dbusOnly && !topcec.backendAvailable
        ? "topCEC Backend Not Available" : "topCEC"
    minimumWidth: 380
    minimumHeight: 500
    pageStack.globalToolBar.style: Kirigami.ApplicationHeaderStyle.None
    readonly property int pageInset: Kirigami.Units.largeSpacing
    property bool settingsDirty: false
    property string submittedSettings: ""

    function settingsValues() {
        return {
            targetOutput: outputField.valueToSave,
            adapter: adapterField.valueToSave,
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
        topcec.rememberInputDraft(root.savedInputPaths())
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

    readonly property string headerStatus: topcec.connectionState === "connecting"
        ? "Connecting"
        : (!topcec.backendAvailable
            ? (topcec.dbusOnly
                ? (root.width < 500 ? "Unavailable" : "Host unavailable")
                : (root.width < 500 ? "Offline" : "Offline configuration"))
            : (topcec.serviceStatus === "configuration-only"
                ? (root.width < 500 ? "Config only" : "Configuration only")
                : (topcec.serviceStatus === "running" ? "Monitoring" : topcec.serviceStatus)))
    readonly property bool serviceHealthy: topcec.backendAvailable
        && topcec.serviceStatus === "running"

    function saveStatusText() {
        if (!topcec.settingsEnabled)
            return "Connect to the host service to save settings."
        if (!outputField.acceptable || !adapterField.acceptable)
            return "Choose a display and CEC adapter."
        if (!inputPaths().length)
            return "Select at least one input device."
        if (!manualInputs.checked && unresolvedInputs().length)
            return "Remove unlisted inputs or enable manual entry."
        if (root.settingsDirty)
            return "Unsaved changes."
        if (topcec.actionMessage.length)
            return topcec.actionMessage
        if (!topcec.dbusOnly && !topcec.backendAvailable)
            return "Settings are saved for the next explicit service start."
        return "All changes saved."
    }

    function copyPageText() {
        return root.title + "\nService: " + root.headerStatus + "\n"
            + root.displayedText(pageContent) + "\n"
            + saveSettingsButton.text + "\n" + settingsSaveStatus.text
    }

    function openDiagnostics() {
        diagnosticsToggle.checked = true
        recoveryScrollTimer.restart()
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

    component DisclosureButton: CopyableButton {
        id: disclosure
        Layout.fillWidth: true
        flat: true
        checkable: true
        contentItem: RowLayout {
            Controls.Label {
                Layout.fillWidth: true
                text: disclosure.text
            }
            Controls.Label {
                text: disclosure.checked ? "⌄" : "›"
                Accessible.ignored: true
            }
        }
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

    component CopyableFormSpinBox: FormCard.FormSpinBoxDelegate {
        TapHandler {
            acceptedButtons: Qt.RightButton
            onTapped: root.showCaption(parent.textFromValue(parent.value, parent.locale))
        }
        Keys.onMenuPressed: root.showCaption(textFromValue(value, locale))
    }

    component EquipmentSelector: CopyableComboBox {
        property var equipment: []
        property bool availabilityKnown: topcec.equipmentAvailabilityKnown
        property bool syncing: false
        property bool manualEntry: false
        property string prompt: "Choose a detected device"
        property string selectedValue: ""
        readonly property bool detected: equipment.some(item => item.path === selectedValue
            || (item.aliases || []).includes(selectedValue))
        property string configuredValue: ""
        property string initialValue: ""
        readonly property bool acceptable: manualEntry
            ? editText.trim().length > 0
            : (detected || (selectedValue === initialValue && configuredValue.length > 0))
        readonly property string valueToSave: manualEntry
            ? editText.trim() : (selectedValue.length ? selectedValue : configuredValue)
        function load(value, showConfigured) {
            configuredValue = value
            initialValue = showConfigured ? value : ""
            synchronize(initialValue)
        }
        editable: manualEntry
        displayText: currentIndex < 0 ? prompt : currentText
        textRole: "label"
        function synchronize(value) {
            syncing = true
            selectedValue = value
            model = root.equipmentChoices(equipment, [value])
            currentIndex = model.findIndex(item => item.path === value)
            editText = value
            syncing = false
        }
        onEquipmentChanged: synchronize(selectedValue)
        onAvailabilityKnownChanged: synchronize(selectedValue)
        onManualEntryChanged: synchronize(selectedValue)
        onActivated: {
            selectedValue = model[index].path
            editText = model[index].path
            root.settingsDirty = true
        }
        onEditTextChanged: {
            if (!syncing && manualEntry) {
                selectedValue = editText
                if (activeFocus)
                    root.settingsDirty = true
            }
        }
    }

    function loadSettings() {
        if (settingsDirty)
            return
        let showConfigured = topcec.configurationSource !== "defaults"
        outputField.load(topcec.setting("target_output"), showConfigured)
        adapterField.load(topcec.setting("cec_port"), showConfigured)
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

    component SurfaceFrame: FormCard.FormCard {
        padding: Kirigami.Units.smallSpacing
    }

    background: Rectangle {
        color: Kirigami.Theme.backgroundColor
    }

    header: Controls.ToolBar {
        id: appHeader
        contentItem: RowLayout {
            spacing: Kirigami.Units.smallSpacing
            Rectangle {
                Layout.preferredWidth: 32
                Layout.preferredHeight: 32
                radius: 8
                color: Kirigami.Theme.alternateBackgroundColor
                Item {
                    anchors.centerIn: parent
                    width: 24
                    height: 24
                    Accessible.ignored: true
                    Rectangle {
                        x: 3
                        y: 3
                        width: 18
                        height: 14
                        radius: 2
                        color: "transparent"
                        border.width: 2
                        border.color: Kirigami.Theme.highlightColor
                    }
                    Rectangle {
                        x: 8
                        y: 18
                        width: 2
                        height: 3
                        color: Kirigami.Theme.highlightColor
                    }
                    Rectangle {
                        x: 14
                        y: 18
                        width: 2
                        height: 3
                        color: Kirigami.Theme.highlightColor
                    }
                }
            }
            SelectableLabel {
                text: "topCEC"
                font.bold: true
                Layout.preferredWidth: 66
                Layout.preferredHeight: 26
                wrapMode: TextEdit.NoWrap
            }
            Item { Layout.fillWidth: true }
            Rectangle {
                Layout.preferredWidth: Math.min(210, Math.max(116, root.headerStatus.length * 8 + 44))
                Layout.preferredHeight: 30
                radius: 16
                color: Kirigami.Theme.alternateBackgroundColor
                border.color: root.serviceHealthy
                    ? Kirigami.Theme.positiveTextColor : Kirigami.Theme.neutralTextColor
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 10
                    anchors.rightMargin: 10
                    spacing: 7
                    Rectangle {
                        Layout.preferredWidth: 7
                        Layout.preferredHeight: 7
                        radius: 4
                        color: root.serviceHealthy
                            ? Kirigami.Theme.positiveTextColor : Kirigami.Theme.neutralTextColor
                    }
                    SelectableLabel {
                        objectName: "serviceStatusPill"
                        Layout.fillWidth: true
                        Layout.preferredHeight: 22
                        font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                        horizontalAlignment: TextEdit.AlignHCenter
                        verticalAlignment: TextEdit.AlignVCenter
                        wrapMode: TextEdit.NoWrap
                        text: root.headerStatus
                        color: root.serviceHealthy
                            ? Kirigami.Theme.positiveTextColor : Kirigami.Theme.neutralTextColor
                    }
                }
            }
            CopyableButton {
                objectName: "copyPageButton"
                text: root.width < 500 ? "Copy" : "Copy page text"
                Accessible.name: "Copy page text"
                onClicked: topcec.copyText(root.copyPageText())
            }
        }
        background: Rectangle {
            color: Kirigami.Theme.backgroundColor
            border.color: Qt.rgba(Kirigami.Theme.textColor.r, Kirigami.Theme.textColor.g,
                                  Kirigami.Theme.textColor.b, 0.14)
        }
    }

    footer: Controls.ToolBar {
        id: applyFooter
        objectName: "applyFooter"
        contentItem: RowLayout {
            spacing: Kirigami.Units.smallSpacing
            CopyableButton {
                id: saveSettingsButton
                objectName: "saveSettingsButton"
                text: "Save and apply"
                Accessible.name: "Save and apply settings"
                Layout.minimumWidth: 132
                enabled: topcec.settingsEnabled && root.equipmentReady
                onClicked: {
                    if (!root.equipmentReady)
                        return
                    let values = root.settingsValues()
                    root.submittedSettings = JSON.stringify(values)
                    values.targetOutput = outputField.valueToSave
                    values.adapter = adapterField.valueToSave
                    values.devices = root.savedInputPaths()
                    topcec.applySettings(values)
                }
            }
            SelectableLabel {
                id: settingsSaveStatus
                objectName: "settingsSaveStatus"
                Layout.fillWidth: true
                verticalAlignment: TextEdit.AlignVCenter
                text: root.saveStatusText()
            }
        }
        background: Rectangle {
            color: Kirigami.Theme.backgroundColor
            border.color: Qt.rgba(Kirigami.Theme.textColor.r, Kirigami.Theme.textColor.g,
                                  Kirigami.Theme.textColor.b, 0.14)
        }
    }

    pageStack.initialPage: FormCard.FormCardPage {
        id: settingsPage
        objectName: "settingsPage"
        title: ""
        actions: [
            Kirigami.Action {
                objectName: "copyPageAction"
                text: "Copy page text"
                icon.name: "edit-copy"
                visible: false
                onTriggered: topcec.copyText(root.copyPageText())
            }
        ]

        ColumnLayout {
            id: pageContent
            objectName: "pageContent"
            Layout.fillWidth: true
            Layout.leftMargin: root.pageInset
            Layout.rightMargin: root.pageInset
            spacing: Kirigami.Units.largeSpacing

            ColumnLayout {
                objectName: "hostCompatibilityPanel"
                Layout.fillWidth: true
                visible: topcec.equipmentRecoveryCommands.length > 0
                spacing: Kirigami.Units.smallSpacing
                SelectableLabel {
                    Layout.fillWidth: true
                    font.bold: true
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
                id: mainViews
                objectName: "mainViews"
                Layout.fillWidth: true
                currentIndex: topcec.dbusOnly && !topcec.backendAvailable ? 0 : 1

                SurfaceFrame {
                    objectName: "setupPanel"
                    Layout.fillWidth: true
                    ColumnLayout {
                        width: parent.width
                        spacing: Kirigami.Units.mediumSpacing
                        SelectableHeading {
                            objectName: "setupHeading"
                            level: 2
                            Layout.fillWidth: true
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
                }

                ColumnLayout {
                    objectName: "connectedOverview"
                    width: parent.width
                    spacing: Kirigami.Units.mediumSpacing

                    ColumnLayout {
                        objectName: "powerCard"
                        Layout.fillWidth: true
                        spacing: 0
                        SurfaceFrame {
                            Layout.fillWidth: true
                            maximumWidth: pageContent.width
                            RowLayout {
                                width: parent.width
                                spacing: Kirigami.Units.mediumSpacing
                                Rectangle {
                                    Layout.preferredWidth: 44
                                    Layout.preferredHeight: 44
                                    radius: 10
                                    color: Kirigami.Theme.alternateBackgroundColor
                                    Item {
                                        anchors.centerIn: parent
                                        width: 30
                                        height: 30
                                        Accessible.ignored: true
                                        Rectangle {
                                            x: 4
                                            y: 4
                                            width: 22
                                            height: 16
                                            radius: 2
                                            color: "transparent"
                                            border.width: 2
                                            border.color: Kirigami.Theme.highlightColor
                                        }
                                        Rectangle {
                                            x: 10
                                            y: 21
                                            width: 2
                                            height: 4
                                            color: Kirigami.Theme.highlightColor
                                        }
                                        Rectangle {
                                            x: 18
                                            y: 21
                                            width: 2
                                            height: 4
                                            color: Kirigami.Theme.highlightColor
                                        }
                                    }
                                }
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 0
                                    SelectableHeading {
                                        objectName: "powerHeading"
                                        level: 3
                                        text: "TV power"
                                    }
                                    SelectableLabel {
                                        objectName: "powerStateLabel"
                                        Layout.fillWidth: true
                                        Layout.preferredHeight: 23
                                        wrapMode: TextEdit.NoWrap
                                        text: topcec.powerState
                                    }
                                }
                                CopyableButton {
                                    objectName: "tvOnButton"
                                    text: "Turn on"
                                    enabled: topcec.simulationMode
                                        || (topcec.backendAvailable && topcec.serviceStatus === "running")
                                    onClicked: topcec.requestPower("on")
                                }
                                CopyableButton {
                                    objectName: "tvStandbyButton"
                                    text: "Standby"
                                    enabled: topcec.simulationMode
                                        || (topcec.backendAvailable
                                            && topcec.serviceStatus === "running"
                                            && topcec.standbyReason === "Automatic standby allowed")
                                    onClicked: topcec.requestPower("off")
                                }
                            }
                        }
                        SelectableLabel {
                            Layout.fillWidth: true
                            visible: topcec.actionMessage.length > 0
                            text: topcec.actionMessage
                        }
                    }

                    SurfaceFrame {
                        objectName: "warningBanner"
                        Layout.fillWidth: true
                        visible: topcec.backendAvailable
                            && (topcec.serviceStatus === "configuration-only"
                                || topcec.standbyReason.startsWith("Automatic standby blocked:"))
                        RowLayout {
                            width: parent.width
                            SelectableLabel {
                                Layout.fillWidth: true
                                text: topcec.inputPermissionMessage.length > 0
                                    ? "Input access is blocked."
                                    : (topcec.serviceStatus === "configuration-only"
                                        ? "Monitoring is inactive."
                                        : "Automatic standby is blocked.")
                            }
                            CopyableButton {
                                objectName: "viewRecoverySteps"
                                text: "View recovery steps"
                                onClicked: root.openDiagnostics()
                            }
                        }
                    }

                    GridLayout {
                        id: configurationGroups
                        objectName: "configurationGroups"
                        Layout.fillWidth: true
                        columns: width >= 660 ? 2 : 1
                        columnSpacing: Kirigami.Units.mediumSpacing
                        rowSpacing: Kirigami.Units.mediumSpacing

                        ColumnLayout {
                            objectName: "equipmentSection"
                            Layout.fillWidth: true
                            Layout.alignment: Qt.AlignTop
                            Layout.minimumWidth: 0
                            Layout.preferredWidth: configurationGroups.columns === 2
                                ? (pageContent.width - configurationGroups.columnSpacing) / 2
                                : pageContent.width
                            Layout.maximumWidth: Layout.preferredWidth
                            spacing: Kirigami.Units.smallSpacing
                            FormCard.FormHeader {
                                objectName: "equipmentHeader"
                                title: "Equipment"
                            }
                            SurfaceFrame {
                                objectName: "equipmentFormCard"
                                Layout.fillWidth: true
                                ColumnLayout {
                                    width: parent.width
                                    spacing: Kirigami.Units.smallSpacing
                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: Kirigami.Units.smallSpacing
                                        SelectableLabel {
                                            Layout.preferredWidth: Kirigami.Units.gridUnit * 5
                                            Layout.preferredHeight: 34
                                            verticalAlignment: TextEdit.AlignVCenter
                                            text: "TV display"
                                        }
                                        EquipmentSelector {
                                            id: outputField
                                            objectName: "outputField"
                                            Layout.fillWidth: true
                                            Layout.minimumWidth: 120
                                            equipment: topcec.detectedOutputs
                                            manualEntry: manualOutput.checked
                                            prompt: "Choose a detected display"
                                        }
                                    }
                                    SelectableLabel {
                                        objectName: "retainedOutput"
                                        Layout.fillWidth: true
                                        visible: !outputField.detected && outputField.valueToSave.length > 0
                                        text: "Saved display: " + root.retainedValue(outputField.valueToSave)
                                    }
                                    CopyableCheckBox {
                                        id: manualOutput
                                        objectName: "manualOutput"
                                        text: "Enter display name manually"
                                        onToggled: root.settingsDirty = true
                                    }
                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: Kirigami.Units.smallSpacing
                                        SelectableLabel {
                                            Layout.preferredWidth: Kirigami.Units.gridUnit * 5
                                            Layout.preferredHeight: 34
                                            verticalAlignment: TextEdit.AlignVCenter
                                            text: "CEC adapter"
                                        }
                                        EquipmentSelector {
                                            id: adapterField
                                            objectName: "adapterField"
                                            Layout.fillWidth: true
                                            Layout.minimumWidth: 120
                                            equipment: topcec.detectedAdapters
                                            manualEntry: manualAdapter.checked
                                            prompt: "Choose a detected CEC adapter"
                                        }
                                    }
                                    SelectableLabel {
                                        objectName: "retainedAdapter"
                                        Layout.fillWidth: true
                                        visible: !adapterField.detected && adapterField.valueToSave.length > 0
                                        text: "Saved adapter: " + root.retainedValue(adapterField.valueToSave)
                                    }
                                    CopyableCheckBox {
                                        id: manualAdapter
                                        objectName: "manualAdapter"
                                        text: "Enter adapter path manually"
                                        onToggled: root.settingsDirty = true
                                    }
                                }
                            }
                            SelectableLabel {
                                Layout.fillWidth: true
                                visible: topcec.configurationSource === "defaults"
                                text: "No saved host configuration. Legacy hardware defaults are not selected."
                            }
                        }

                        ColumnLayout {
                            objectName: "standbySection"
                            Layout.fillWidth: true
                            Layout.alignment: Qt.AlignTop
                            Layout.minimumWidth: 0
                            Layout.preferredWidth: configurationGroups.columns === 2
                                ? (pageContent.width - configurationGroups.columnSpacing) / 2
                                : pageContent.width
                            Layout.maximumWidth: Layout.preferredWidth
                            spacing: Kirigami.Units.smallSpacing
                            FormCard.FormHeader {
                                objectName: "standbyHeader"
                                title: "Automatic standby"
                            }
                            SurfaceFrame {
                                objectName: "standbyFormCard"
                                Layout.fillWidth: true
                                ColumnLayout {
                                    width: parent.width
                                    spacing: Kirigami.Units.smallSpacing
                                    RowLayout {
                                        Layout.fillWidth: true
                                        SelectableLabel {
                                            Layout.preferredWidth: Kirigami.Units.gridUnit * 5
                                            text: "Idle timeout"
                                        }
                                        CopyableComboBox {
                                            id: timeoutMode
                                            objectName: "timeoutMode"
                                            Layout.fillWidth: true
                                            Accessible.name: "Idle timeout"
                                            model: ["KDE-managed", "Custom", "Disabled"]
                                            onActivated: root.settingsDirty = true
                                        }
                                    }
                                    RowLayout {
                                        Layout.fillWidth: true
                                        visible: timeoutMode.currentIndex === 1
                                        SelectableLabel {
                                            Layout.fillWidth: true
                                            text: "Minutes"
                                        }
                                        Controls.SpinBox {
                                            id: timeoutMinutes
                                            objectName: "timeoutMinutes"
                                            Accessible.name: "Minutes"
                                            editable: true
                                            from: 1
                                            to: 1440
                                            onValueModified: root.settingsDirty = true
                                            TapHandler {
                                                acceptedButtons: Qt.RightButton
                                                onTapped: root.showCaption(timeoutMinutes.textFromValue(
                                                    timeoutMinutes.value, timeoutMinutes.locale))
                                            }
                                            Keys.onMenuPressed: root.showCaption(textFromValue(value, locale))
                                        }
                                    }
                                    DisclosureButton {
                                        id: inputChooserToggle
                                        objectName: "inputChooserToggle"
                                        readonly property string selectionSummary: root.inputPaths().length + " selected"
                                            + (root.unresolvedInputs().length
                                                ? " · " + root.unresolvedInputs().length + " unlisted" : "")
                                        text: "Input devices · " + selectionSummary
                                        Accessible.description: checked
                                            ? "Input device checklist expanded"
                                            : "Input device checklist collapsed"
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
                                    CopyableButton {
                                        objectName: "copySelectedInputs"
                                        text: "Copy paths"
                                        visible: inputChooserToggle.checked
                                        enabled: root.inputPaths().length > 0
                                        onClicked: topcec.copyText(root.inputPaths().join("\n"))
                                    }
                                    SelectableLabel {
                                        objectName: "inputSaveHelp"
                                        Layout.fillWidth: true
                                        visible: inputChooserToggle.checked
                                        text: !topcec.backendAvailable
                                            ? (topcec.dbusOnly
                                                ? "Input changes remain pending until the host connects."
                                                : "Input changes remain pending until the host connects or you save offline.")
                                            : topcec.liveSettingsAvailable
                                                ? "Input changes apply automatically without restarting."
                                                : "Input changes save automatically and may restart the service."
                                    }
                                    SelectableLabel {
                                        objectName: "retainedInputs"
                                        Layout.fillWidth: true
                                        visible: inputChooserToggle.checked && root.unresolvedInputs().length > 0
                                        text: "Unlisted input paths\n"
                                            + root.unresolvedInputs().map(path => root.retainedValue(path)).join("\n")
                                    }
                                    CopyableButton {
                                        objectName: "removeUndetectedInputs"
                                        text: "Remove unlisted inputs"
                                        visible: inputChooserToggle.checked && root.unresolvedInputs().length > 0
                                        onClicked: {
                                            devicesField.text = root.inputPaths().filter(path => root.inputDetected(path)).join("\n")
                                            root.settingsDirty = true
                                        }
                                    }
                                    CopyableCheckBox {
                                        id: manualInputs
                                        objectName: "manualInputs"
                                        visible: inputChooserToggle.checked
                                        text: "Enter input paths manually"
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
                                }
                            }
                        }
                    }

                    DisclosureButton {
                        id: advancedToggle
                        objectName: "advancedToggle"
                        text: "Advanced"
                        Accessible.name: "Advanced settings"
                        Accessible.description: checked ? "Expanded" : "Collapsed"
                    }
                    SurfaceFrame {
                        objectName: "advancedPanel"
                        Layout.fillWidth: true
                        visible: advancedToggle.checked
                        ColumnLayout {
                            width: parent.width
                            CopyableCheckBox {
                                objectName: "simulateManualActions"
                                text: "Simulate manual actions"
                                checked: topcec.simulationMode
                                onToggled: topcec.setSimulationMode(checked)
                            }
                            CopyableFormSpinBox {
                                id: deadzoneField
                                objectName: "deadzoneField"
                                label: "Axis deadzone (%)"
                                Layout.fillWidth: true
                                from: 1
                                to: 25
                                onValueModified: root.settingsDirty = true
                            }
                            CopyableFormSpinBox {
                                id: rzDeadzoneField
                                objectName: "rzDeadzoneField"
                                label: "ABS_RZ deadzone (%)"
                                Layout.fillWidth: true
                                from: 1
                                to: 25
                                onValueModified: root.settingsDirty = true
                            }
                            SelectableLabel {
                                Layout.fillWidth: true
                                objectName: "muteLabelsCaption"
                                text: "Firefox mute-tab labels"
                            }
                            Controls.TextArea {
                                id: labelsField
                                objectName: "labelsField"
                                Layout.fillWidth: true
                                Layout.preferredHeight: 56
                                Accessible.name: "Firefox mute-tab labels (one per line)"
                                placeholderText: "One per line"
                                selectByMouse: true
                                onTextChanged: {
                                    if (activeFocus) root.settingsDirty = true
                                }
                            }
                        }
                    }

                    DisclosureButton {
                        id: diagnosticsToggle
                        objectName: "diagnosticsToggle"
                        text: "Diagnostics"
                        Accessible.name: "Service diagnostics"
                        Accessible.description: checked ? "Expanded" : "Collapsed"
                    }
                    SurfaceFrame {
                        id: diagnosticsPanel
                        objectName: "diagnosticsPanel"
                        Layout.fillWidth: true
                        visible: diagnosticsToggle.checked
                        ColumnLayout {
                            width: parent.width
                            SelectableLabel {
                                Layout.fillWidth: true
                                text: "Service: " + topcec.serviceStatus
                            }
                            SelectableLabel {
                                Layout.fillWidth: true
                                text: topcec.connectionMessage
                            }
                            SelectableLabel {
                                Layout.fillWidth: true
                                text: "TV power: " + topcec.powerState
                            }
                            SelectableLabel {
                                objectName: "standbyDiagnostics"
                                Layout.fillWidth: true
                                text: topcec.standbyReason
                            }
                            SelectableLabel {
                                objectName: "actionDiagnostics"
                                Layout.fillWidth: true
                                visible: topcec.actionMessage.length > 0
                                text: topcec.actionMessage
                            }
                            SelectableLabel {
                                Layout.fillWidth: true
                                text: topcec.equipmentMessage
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
                            SelectableLabel {
                                Layout.fillWidth: true
                                visible: topcec.equipmentRecoveryCommands.length > 0
                                text: topcec.compatibilityMessage
                            }
                            SelectableLabel {
                                objectName: "diagnosticsHostUpdateInstructions"
                                Layout.fillWidth: true
                                visible: topcec.equipmentRecoveryCommands.length > 0
                                text: "Run the copied update command in a host terminal from any directory, then restart the service."
                            }
                            Controls.TextArea {
                                objectName: "diagnosticsEquipmentRecoveryCommands"
                                Layout.fillWidth: true
                                visible: topcec.equipmentRecoveryCommands.length > 0
                                readOnly: true
                                selectByMouse: true
                                wrapMode: TextEdit.WrapAnywhere
                                text: topcec.equipmentRecoveryCommands
                            }
                            CopyableButton {
                                objectName: "copyDiagnosticsEquipmentRecovery"
                                visible: topcec.equipmentRecoveryCommands.length > 0
                                text: "Copy host update command"
                                onClicked: topcec.copyText(topcec.equipmentRecoveryCommands)
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
        }
    }

    Timer {
        id: recoveryScrollTimer
        interval: 30
        repeat: false
        onTriggered: {
            let flickable = settingsPage.flickable
            if (!flickable || !diagnosticsPanel.visible)
                return
            let bottom = diagnosticsPanel.mapToItem(
                flickable.contentItem, 0, 0).y + diagnosticsPanel.height
            flickable.contentY = Math.max(0, Math.min(
                bottom - flickable.height, flickable.contentHeight - flickable.height))
        }
    }

    Timer {
        interval: topcec.backendAvailable ? 5000 : 30000
        running: true
        repeat: true
        onTriggered: topcec.refresh()
    }
}
