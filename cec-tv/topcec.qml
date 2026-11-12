// SPDX-License-Identifier: GPL-3.0-or-later
import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.kirigamiaddons.formcard as FormCard

Kirigami.ApplicationWindow {
    id: root
    title: root.setupRequired
        ? "topCEC Backend Not Available" : "topCEC"
    width: 1060
    height: 800
    minimumWidth: 380
    minimumHeight: 500
    pageStack.globalToolBar.style: Kirigami.ApplicationHeaderStyle.None
    readonly property int pageInset: Kirigami.Units.largeSpacing
    property int currentSection: 0
    readonly property bool setupRequired: topcec.dbusOnly && !topcec.backendAvailable
    readonly property var sectionNames: ["Overview", "Display", "Standby", "Input", "Diagnostics"]
    property bool settingsDirty: false
    property string submittedSettings: ""
    property var axisDraft: ({})
    property real defaultAxisDeadzone: 2
    property real defaultRzDeadzone: 5

    globalDrawer: Kirigami.GlobalDrawer {
        id: navigationDrawer
        objectName: "navigationDrawer"
        title: "topCEC"
        titleIcon: topcec.applicationIcon
        modal: !root.wideScreen
        handleVisible: false
        onModalChanged: {
            if (!modal) {
                Qt.callLater(() => {
                    if (!navigationDrawer.modal)
                        navigationDrawer.drawerOpen = true
                })
            }
        }
        Binding {
            target: navigationDrawer.handle
            property: "visible"
            value: false
        }
        header: Controls.ToolBar {
            objectName: "appIdentityHeader"
            implicitHeight: pageToolbar.implicitHeight
            leftPadding: Kirigami.Units.largeSpacing
            rightPadding: Kirigami.Units.largeSpacing
            contentItem: RowLayout {
                spacing: Kirigami.Units.smallSpacing
                Controls.ToolButton {
                    objectName: "drawerNavigationButton"
                    visible: navigationDrawer.modal
                    icon.name: "application-menu"
                    text: "Hide navigation"
                    display: Controls.AbstractButton.IconOnly
                    Accessible.name: text
                    onClicked: navigationDrawer.drawerOpen = false
                }
                Kirigami.Icon {
                    objectName: "appIdentityLogo"
                    source: navigationDrawer.titleIcon
                    Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
                    Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium
                    Accessible.ignored: true
                }
                Kirigami.Heading {
                    objectName: "appIdentityName"
                    Layout.fillWidth: true
                    text: navigationDrawer.title
                    level: 2
                    elide: Text.ElideRight
                }

            }
        }
        actions: [
            Kirigami.Action {
                objectName: "overviewNavigation"
                text: "Overview"
                icon.name: "view-dashboard"
                checked: root.currentSection === 0
                onTriggered: root.currentSection = 0
            },
            Kirigami.Action {
                objectName: "equipmentNavigation"
                text: "Display"
                icon.name: "video-display"
                checked: root.currentSection === 1
                onTriggered: root.currentSection = 1
            },
            Kirigami.Action {
                objectName: "standbyNavigation"
                text: "Standby"
                icon.name: "preferences-system-power-management"
                checked: root.currentSection === 2
                onTriggered: root.currentSection = 2
            },
            Kirigami.Action {
                objectName: "inputNavigation"
                text: "Input"
                icon.name: "input-keyboard"
                checked: root.currentSection === 3
                onTriggered: root.currentSection = 3
            },
            Kirigami.Action {
                objectName: "diagnosticsNavigation"
                text: "Diagnostics"
                icon.name: "utilities-log-viewer"
                checked: root.currentSection === 4
                onTriggered: root.openDiagnostics()
            }
        ]
    }

    onCurrentSectionChanged: {
        if (settingsPage.flickable)
            settingsPage.flickable.contentY = 0
    }

    function settingsValues() {
        return {
            targetOutput: outputField.valueToSave,
            adapter: adapterField.valueToSave,
            timeoutMode: timeoutMode.currentIndex === 0 ? "kde"
                : (timeoutMode.currentIndex === 1 ? "custom" : "never"),
            timeoutMinutes: timeoutMinutes.value,
            devices: devicesField.text,
            considerInputDevices: considerInputDevices.checked,
            mouseOutput: mouseOutput.selectedOutput.length ? mouseOutput.selectedOutput : null,
            muteLabels: labelsField.text,
            axisDeadzone: defaultAxisDeadzone,
            rzDeadzone: defaultRzDeadzone,
            deviceAxisDeadzones: axisDraft
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

    function inputSelectionSummary() {
        let summary = inputPaths().length + " selected"
        let unlistedCount = unresolvedInputs().length
        if (unlistedCount)
            summary += " · " + unlistedCount + " unlisted"
        return summary
    }

    function retainedValue(value) {
        return value + (topcec.equipmentAvailabilityKnown
            ? " (unavailable / not detected)" : " (availability unknown)")
    }

    function equipmentSelectionStatus(selector, noun) {
        let status = selector.detected ? "Detected · " + selector.selectedValue : ""
        let saved = selector.initialValue
        if (saved.length && !selector.equipment.some(item => item.path === saved
                || (item.aliases || []).includes(saved))) {
            if (status.length)
                status += "\n"
            status += "Saved " + noun + ": " + root.retainedValue(saved)
        }
        if (selector.manualEntry && !selector.detected
                && selector.valueToSave.length && selector.valueToSave !== saved) {
            if (status.length)
                status += "\n"
            status += "Manual " + noun + ": " + root.retainedValue(selector.valueToSave)
        }
        return status
    }

    function equipmentSummary(selector, emptyMessage, unknownMessage, chooseMessage) {
        if (selector.detected)
            return selector.selectedValue
        if (selector.manualEntry && selector.valueToSave.length)
            return root.retainedValue(selector.valueToSave)
        if (selector.equipment.length)
            return chooseMessage
        return selector.availabilityKnown ? emptyMessage : unknownMessage
    }

    readonly property bool equipmentReady: outputField.acceptable && adapterField.acceptable
        && (!considerInputDevices.checked || inputPaths().length > 0)

    function inputPaths() {
        return devicesField.text.split("\n").map(path => path.trim()).filter(path => path.length)
    }

    function inputAccessBlocked(device) {
        return topcec.blockedInputPath.length > 0
            && (device.path === topcec.blockedInputPath
                || (device.aliases || []).includes(topcec.blockedInputPath))
    }

    function savedInputPaths() {
        let paths = inputPaths().map(path => {
            let item = topcec.detectedInputs.find(device => device.path === path || (device.aliases || []).includes(path))
            return item ? item.path : path
        })
        return [...new Set(paths)].join("\n")
    }

    function selectedAxisDevices() {
        return topcec.detectedInputs.filter(device =>
            inputPaths().some(path => path === device.path || (device.aliases || []).includes(path)))
    }

    function selectedAxisRows() {
        let rows = []
        for (let device of selectedAxisDevices()) {
            for (let axis of (device.axes || []))
                rows.push({device: device, axis: axis})
        }
        return rows
    }

    function axisPath(device) {
        return [device.path, ...(device.aliases || [])].find(path => axisDraft[path] !== undefined)
            || device.path
    }

    function axisValue(device, axis) {
        let overrides = axisDraft[axisPath(device)] || {}
        return overrides[String(axis.code)] !== undefined ? overrides[String(axis.code)]
            : (axis.code === 5 ? defaultRzDeadzone : defaultAxisDeadzone)
    }

    function setAxisValue(device, axis, value) {
        let draft = JSON.parse(JSON.stringify(axisDraft))
        let path = axisPath(device)
        if (!draft[path])
            draft[path] = {}
        draft[path][String(axis.code)] = value
        axisDraft = draft
        settingsDirty = true
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

    component DiagnosticState: ColumnLayout {
        id: state
        property string label
        property string value
        property color stateColor: Kirigami.Theme.disabledTextColor
        Layout.fillWidth: true
        Layout.alignment: Qt.AlignTop
        spacing: Kirigami.Units.smallSpacing
        SelectableLabel {
            Layout.fillWidth: true
            text: state.label
        }
        RowLayout {
            Layout.fillWidth: true
            Rectangle {
                Layout.preferredWidth: Kirigami.Units.smallSpacing * 2
                Layout.preferredHeight: width
                radius: width / 2
                color: state.stateColor
            }
            SelectableLabel {
                Layout.fillWidth: true
                font.bold: true
                text: state.value
            }
        }
    }

    component DiagnosticDevice: RowLayout {
        id: deviceRow
        property string label
        property string description
        Layout.fillWidth: true
        Layout.margins: Kirigami.Units.smallSpacing
        spacing: Kirigami.Units.mediumSpacing
        SelectableLabel {
            Layout.preferredWidth: Kirigami.Units.gridUnit * 7
            Layout.minimumWidth: 0
            Layout.alignment: Qt.AlignTop
            text: deviceRow.label
        }
        SelectableLabel {
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            text: deviceRow.description
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
            return item.text + (typeof item.description === "string" && item.description.length
                ? "\n" + item.description : "")
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
    readonly property bool standbyBlocked: topcec.standbyReason.startsWith("Automatic standby blocked:")
    readonly property string standbyBlockReason: root.standbyBlocked
        ? topcec.standbyReason.slice("Automatic standby blocked:".length).trim() : ""
    readonly property bool serviceHealthy: topcec.backendAvailable
        && topcec.serviceStatus === "running"
    readonly property bool monitoringWarning: topcec.backendAvailable
        && (topcec.serviceStatus === "configuration-only" || root.standbyBlocked)
    readonly property string monitoringWarningText: root.standbyBlocked
        ? "Automatic standby is blocked: "
            + (root.standbyBlockReason.length ? root.standbyBlockReason : "No reason was reported.")
            + (topcec.serviceStatus === "configuration-only"
                ? (/[^.!?]$/.test(root.standbyBlockReason) ? ". " : " ") + "Monitoring is inactive." : "")
        : (topcec.inputPermissionMessage.length > 0
            ? "Input access is blocked. Monitoring is inactive."
            : "Monitoring is inactive.")

    readonly property string timeoutSummary: timeoutMode.currentIndex === 1
        ? timeoutMinutes.value + (timeoutMinutes.value === 1 ? " minute" : " minutes")
        : timeoutMode.currentText
    readonly property string hostConnectionStatus: topcec.backendAvailable ? "Connected"
        : (topcec.connectionState === "connecting" ? "Connecting" : "Unavailable")
    readonly property string monitoringStatus: !topcec.backendAvailable ? "Unknown"
        : (root.serviceHealthy ? "Active"
            : (topcec.serviceStatus === "configuration-only" ? "Inactive" : topcec.serviceStatus))

    function detectedDeviceText(devices, includePath) {
        return devices.length ? devices.map(device => {
            let label = device.label
            if (includePath && label !== device.path)
                label += " · " + device.path
            if (inputAccessBlocked(device))
                label += " · Access blocked"
            return label
        }).join("\n") : (topcec.equipmentAvailabilityKnown ? "None detected" : "Detection unavailable")
    }

    function diagnosticReport() {
        let sections = [
            root.title + " — Diagnostics",
            "Host service: " + root.hostConnectionStatus,
            "Monitoring: " + root.monitoringStatus,
            "TV power: " + topcec.powerState,
            root.monitoringWarning ? root.monitoringWarningText
                : (topcec.backendAvailable ? topcec.standbyReason : topcec.connectionMessage),
            topcec.actionMessage,
            topcec.inputPermissionMessage,
            topcec.inputPermissionCommand,
            topcec.compatibilityMessage,
            topcec.equipmentRecoveryCommands,
            "TV display: " + root.detectedDeviceText(topcec.detectedOutputs, true),
            "CEC adapter: " + root.detectedDeviceText(topcec.detectedAdapters, true),
            "Input devices: " + root.inputSelectionSummary() + "\n"
                + root.detectedDeviceText(topcec.detectedInputs, true),
            topcec.equipmentAvailabilityKnown ? "" : topcec.equipmentMessage,
            "Host service status\n" + topcec.diagnostics
        ]
        return sections.filter(text => text.length).join("\n")
    }

    function saveStatusText() {
        if (!topcec.settingsEnabled)
            return "Connect to the host service to save settings."
        if (!outputField.acceptable || !adapterField.acceptable)
            return "Choose a display and CEC adapter."
        if (considerInputDevices.checked && !inputPaths().length)
            return "Select at least one input device."
        if (root.settingsDirty)
            return "Unsaved changes."
        if (topcec.actionMessage.length)
            return topcec.actionMessage
        if (!topcec.dbusOnly && !topcec.backendAvailable)
            return "Settings are saved for the next explicit service start."
        return "All changes saved."
    }

    readonly property bool onDiagnosticsPage: root.currentSection === 4 && !root.setupRequired

    function copyPageText() {
        if (root.onDiagnosticsPage)
            return root.diagnosticReport()
        return root.title + "\n" + settingsPage.title + "\nService: " + root.headerStatus + "\n"
            + root.displayedText(pageContent) + "\n"
            + (applyFooter.visible ? saveSettingsButton.text + "\n" + settingsSaveStatus.text : "")
    }

    function copyCurrentPage() {
        topcec.copyText(root.copyPageText())
        if (root.onDiagnosticsPage)
            root.showPassiveNotification("Diagnostics copied")
    }

    function openDiagnostics() {
        root.currentSection = 4
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

    component CopyableFormButton: FormCard.FormButtonDelegate {
        TapHandler {
            acceptedButtons: Qt.RightButton
            onTapped: root.showCaption(parent.text)
        }
        Keys.onMenuPressed: root.showCaption(text)
    }

    component DisclosureButton: CopyableFormButton {
        id: disclosure
        Layout.fillWidth: true
        checkable: true
        trailingLogo.direction: checked ? Qt.DownArrow : Qt.RightArrow
        Accessible.description: checked ? "Expanded" : "Collapsed"
        Accessible.onPressAction: disclosure.click()
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
        property bool automaticSelection: false
        property bool explicitSelection: false
        property string choosePrompt: "Choose a detected device"
        property string emptyPrompt: "No applicable hardware has been detected"
        property string unknownPrompt: "Hardware detection unavailable"
        readonly property string prompt: equipment.length > 0
            ? choosePrompt : (availabilityKnown ? emptyPrompt : unknownPrompt)
        property string selectedValue: ""
        readonly property bool detected: equipment.some(item => item.path === selectedValue
            || (item.aliases || []).includes(selectedValue))
        property string configuredValue: ""
        property string initialValue: ""
        readonly property bool acceptable: manualEntry
            ? editText.trim().length > 0
            : (detected || (automaticSelection && selectedValue.length > 0)
                || (selectedValue === initialValue && configuredValue.length > 0))
        readonly property string valueToSave: manualEntry
            ? editText.trim() : (selectedValue.length ? selectedValue : configuredValue)
        function load(value, showConfigured) {
            configuredValue = value
            initialValue = showConfigured ? value : ""
            automaticSelection = false
            explicitSelection = false
            synchronize(initialValue)
        }
        editable: manualEntry
        displayText: currentIndex < 0 ? prompt : currentText
        textRole: "label"
        function synchronize(value) {
            syncing = true
            let selection = value
            if (automaticSelection) {
                if (equipment.length === 1)
                    selection = equipment[0].path
            } else if (!explicitSelection && !manualEntry && equipment.length === 1
                    && (!selection.length || !equipment.some(item => item.path === selection
                        || (item.aliases || []).includes(selection)))) {
                selection = equipment[0].path
                automaticSelection = true
            }
            selectedValue = selection
            model = root.equipmentChoices(equipment, [selection])
            currentIndex = model.findIndex(item => item.path === selection)
            editText = selection
            syncing = false
        }
        onEquipmentChanged: synchronize(selectedValue)
        onAvailabilityKnownChanged: synchronize(selectedValue)
        onManualEntryChanged: synchronize(selectedValue)
        onActivated: function(index) {
            automaticSelection = false
            explicitSelection = true
            selectedValue = model[index].path
            editText = model[index].path
            root.settingsDirty = true
        }
        onEditTextChanged: {
            if (!syncing && manualEntry) {
                automaticSelection = false
                explicitSelection = true
                selectedValue = editText
                if (activeFocus)
                    root.settingsDirty = true
            }
        }
    }

    function loadSettings() {
        if (settingsDirty)
            return
        let showConfigured = topcec.configurationSource === "saved"
        outputField.load(topcec.setting("target_output"), showConfigured)
        adapterField.load(topcec.setting("cec_port"), showConfigured)
        timeoutMode.currentIndex = topcec.usesKdeTimeout() ? 0
            : (topcec.setting("timeout_seconds") === null ? 2 : 1)
        timeoutMinutes.value = topcec.timeoutMinutes()
        considerInputDevices.checked = topcec.setting("consider_input_devices")
        mouseOutput.selectedOutput = topcec.setting("mouse_output") || ""
        devicesField.text = topcec.deviceList()
        labelsField.text = topcec.muteLabelList()
        defaultAxisDeadzone = topcec.setting("axis_deadzone_percent")
        defaultRzDeadzone = topcec.setting("rz_deadzone_percent")
        axisDraft = JSON.parse(JSON.stringify(topcec.setting("device_axis_deadzones") || {}))
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

    component FullWidthFrame: SurfaceFrame {
        maximumWidth: width
    }

    background: Rectangle {
        color: Kirigami.Theme.backgroundColor
    }

    pageStack.initialPage: FormCard.FormCardPage {
        id: settingsPage
        objectName: "settingsPage"
        title: root.setupRequired
            ? "Host service" : root.sectionNames[root.currentSection]
        header: Controls.ToolBar {
            id: pageToolbar
            objectName: "pageToolbar"
            contentItem: RowLayout {
                Controls.ToolButton {
                    objectName: "navigationButton"
                    icon.name: "application-menu"
                    text: navigationDrawer.drawerOpen ? "Hide navigation" : "Show navigation"
                    display: Controls.AbstractButton.IconOnly
                    Accessible.name: text
                    onClicked: navigationDrawer.drawerOpen = !navigationDrawer.drawerOpen
                }
                Kirigami.Heading {
                    Layout.fillWidth: true
                    text: settingsPage.title
                    level: 2
                    elide: Text.ElideRight
                }
                CopyableButton {
                    objectName: "copyPageButton"
                    text: root.onDiagnosticsPage ? "Copy diagnostics"
                        : (root.width < 500 ? "Copy" : "Copy page text")
                    icon.name: "edit-copy"
                    flat: true
                    Accessible.name: root.onDiagnosticsPage ? "Copy diagnostics" : "Copy page text"
                    onClicked: root.copyCurrentPage()
                }
            }
        }
        footer: Controls.ToolBar {
            id: applyFooter
            objectName: "applyFooter"
            visible: !root.setupRequired && (root.settingsDirty || !root.equipmentReady
                || (!topcec.dbusOnly && !topcec.backendAvailable)
                || (topcec.serviceStatus === "configuration-only" && !topcec.monitoringRetryAvailable))
            contentItem: RowLayout {
                spacing: Kirigami.Units.smallSpacing
                SelectableLabel {
                    id: settingsSaveStatus
                    objectName: "settingsSaveStatus"
                    Layout.fillWidth: true
                    verticalAlignment: TextEdit.AlignVCenter
                    text: root.saveStatusText()
                }
                CopyableButton {
                    id: saveSettingsButton
                    objectName: "saveSettingsButton"
                    text: "Save and apply"
                    icon.name: "dialog-ok-apply"
                    Accessible.name: "Save and apply settings"
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
            }
        }
        actions: [
            Kirigami.Action {
                objectName: "copyPageAction"
                text: root.onDiagnosticsPage ? "Copy diagnostics" : "Copy page text"
                icon.name: "edit-copy"
                visible: false
                onTriggered: root.copyCurrentPage()
            }
        ]

        ColumnLayout {
            id: pageContent
            objectName: "pageContent"
            Layout.fillWidth: true
            Layout.maximumWidth: root.onDiagnosticsPage ? 860 : 760
            Layout.alignment: Qt.AlignHCenter
            Layout.leftMargin: root.pageInset
            Layout.rightMargin: root.pageInset
            Layout.topMargin: root.pageInset
            Layout.bottomMargin: root.pageInset
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

            ColumnLayout {
                id: mainViews
                objectName: "mainViews"
                Layout.fillWidth: true

                SurfaceFrame {
                    objectName: "setupPanel"
                    visible: root.setupRequired
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
                    visible: !root.setupRequired
                    width: parent.width
                    spacing: Kirigami.Units.mediumSpacing

                    SelectableLabel {
                        objectName: "actionFeedback"
                        Layout.fillWidth: true
                        visible: root.currentSection !== 3 && root.currentSection !== 4
                            && topcec.actionMessage.length > 0
                        text: topcec.actionMessage
                    }

                    FullWidthFrame {
                        objectName: "powerCard"
                        Layout.fillWidth: true
                        visible: root.currentSection === 0
                        GridLayout {
                            width: parent.width
                            columns: width >= 420 ? 2 : 1
                            columnSpacing: Kirigami.Units.mediumSpacing
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: Kirigami.Units.smallSpacing
                                SelectableHeading {
                                    objectName: "powerHeading"
                                    level: 2
                                    text: "TV power"
                                }
                                SelectableLabel {
                                    objectName: "powerStateLabel"
                                    Layout.fillWidth: true
                                    font.bold: true
                                    text: topcec.powerState
                                }
                                RowLayout {
                                    objectName: "monitoringStatusRow"
                                    Layout.fillWidth: true
                                    SelectableLabel {
                                        objectName: "serviceStatusLabel"
                                        Layout.fillWidth: true
                                        text: root.headerStatus
                                        color: root.serviceHealthy
                                            ? Kirigami.Theme.positiveTextColor : Kirigami.Theme.textColor
                                    }
                                }
                            }
                            RowLayout {
                                CopyableButton {
                                    objectName: "tvOnButton"
                                    text: "Turn on"
                                    icon.name: "system-shutdown"
                                    enabled: topcec.backendAvailable && topcec.serviceStatus === "running"
                                    onClicked: topcec.requestPower("on")
                                }
                                CopyableButton {
                                    objectName: "tvStandbyButton"
                                    text: "Standby"
                                    icon.name: "system-suspend"
                                    enabled: topcec.backendAvailable
                                        && topcec.serviceStatus === "running"
                                        && topcec.standbyReason === "Automatic standby allowed"
                                    onClicked: topcec.requestPower("off")
                                }
                            }
                        }
                    }

                    FullWidthFrame {
                        Layout.fillWidth: true
                        visible: (root.currentSection === 0 || root.currentSection === 2)
                            && root.monitoringWarning
                        ColumnLayout {
                            width: parent.width
                            Kirigami.InlineMessage {
                                objectName: "warningBanner"
                                Layout.fillWidth: true
                                visible: true
                                type: Kirigami.MessageType.Warning
                                text: root.monitoringWarningText
                            }
                            CopyableButton {
                                objectName: "viewRecoverySteps"
                                Layout.alignment: Qt.AlignRight
                                text: "View recovery steps"
                                icon.name: "help-hint"
                                onClicked: root.openDiagnostics()
                            }
                        }
                    }

                    ColumnLayout {
                        objectName: "overviewSummary"
                        Layout.fillWidth: true
                        visible: root.currentSection === 0
                        spacing: Kirigami.Units.smallSpacing
                        SelectableHeading {
                            level: 3
                            text: "Equipment and standby"
                        }
                        FullWidthFrame {
                            padding: 0
                            Layout.fillWidth: true
                            FormCard.FormTextDelegate {
                                id: displaySummary
                                objectName: "displaySummary"
                                visible: outputField.detected
                                    || (manualOutput.checked && outputField.valueToSave.length > 0)
                                text: "TV display"
                                description: root.equipmentSummary(
                                    outputField, "No display detected", "Display detection unavailable",
                                    "Choose a detected display in the Display section")
                                leading: Kirigami.Icon {
                                    source: "video-display"
                                    implicitWidth: Kirigami.Units.iconSizes.medium
                                    implicitHeight: Kirigami.Units.iconSizes.medium
                                }
                            }
                            FormCard.FormDelegateSeparator {
                                visible: displaySummary.visible && adapterSummary.visible
                            }
                            FormCard.FormTextDelegate {
                                id: adapterSummary
                                objectName: "adapterSummary"
                                visible: true
                                text: "CEC adapter"
                                description: root.equipmentSummary(
                                    adapterField, "No CEC adapter detected",
                                    "CEC adapter detection unavailable",
                                    "Choose a detected CEC adapter in the Display section")
                                leading: Kirigami.Icon {
                                    source: "network-wired"
                                    implicitWidth: Kirigami.Units.iconSizes.medium
                                    implicitHeight: Kirigami.Units.iconSizes.medium
                                }
                            }
                            FormCard.FormDelegateSeparator {
                                visible: displaySummary.visible || adapterSummary.visible
                            }
                            CopyableFormButton {
                                objectName: "configureEquipmentButton"
                                text: "Configure display and adapter…"
                                icon.name: "configure"
                                onClicked: root.currentSection = 1
                            }
                            FormCard.FormDelegateSeparator {}
                            CopyableFormButton {
                                text: "Automatic standby"
                                description: (root.monitoringWarning ? "Blocked · " : "") + root.timeoutSummary
                                icon.name: "preferences-system-power-management"
                                onClicked: root.currentSection = 2
                            }
                            FormCard.FormDelegateSeparator {}
                            CopyableFormButton {
                                objectName: "configureInputButton"
                                text: "Configure input devices…"
                                description: root.inputSelectionSummary()
                                icon.name: "input-keyboard"
                                onClicked: {
                                    root.currentSection = 3
                                }
                            }
                        }
                    }

                    GridLayout {
                        Layout.fillWidth: true
                        visible: root.currentSection === 1 || root.currentSection === 2
                            || root.currentSection === 3
                        columns: 1
                        columnSpacing: Kirigami.Units.mediumSpacing
                        rowSpacing: Kirigami.Units.mediumSpacing

                        ColumnLayout {
                            objectName: "equipmentSection"
                            visible: root.currentSection === 1
                            Layout.fillWidth: true
                            Layout.alignment: Qt.AlignTop
                            Layout.minimumWidth: 0
                            Layout.preferredWidth: pageContent.width
                            Layout.maximumWidth: Layout.preferredWidth
                            spacing: Kirigami.Units.smallSpacing
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
                                            choosePrompt: "Choose a detected display"
                                            emptyPrompt: "No display has been detected"
                                            unknownPrompt: "Display detection unavailable"
                                        }
                                    }
                                    SelectableLabel {
                                        objectName: "retainedOutput"
                                        Layout.fillWidth: true
                                        visible: text.length > 0
                                        text: root.equipmentSelectionStatus(outputField, "display")
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
                                            choosePrompt: "Choose a detected CEC adapter"
                                            emptyPrompt: "No CEC adapter has been detected"
                                            unknownPrompt: "CEC adapter detection unavailable"
                                        }
                                    }
                                    SelectableLabel {
                                        objectName: "retainedAdapter"
                                        Layout.fillWidth: true
                                        visible: text.length > 0
                                        text: root.equipmentSelectionStatus(adapterField, "adapter")
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
                            visible: root.currentSection === 2
                            Layout.fillWidth: true
                            Layout.alignment: Qt.AlignTop
                            Layout.minimumWidth: 0
                            Layout.preferredWidth: pageContent.width
                            Layout.maximumWidth: Layout.preferredWidth
                            spacing: Kirigami.Units.smallSpacing
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
                                            model: [topcec.plasmaTimeoutLabel, "Custom", "Disabled"]
                                            onActivated: root.settingsDirty = true
                                        }
                                    }
                                    RowLayout {
                                        Layout.fillWidth: true
                                        visible: timeoutMode.currentIndex === 1
                                        SelectableLabel {
                                            Layout.fillWidth: true
                                            text: "Put TV in standby after"
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
                                        SelectableLabel { text: "minutes" }
                                    }
                                    CopyableCheckBox {
                                        id: considerInputDevices
                                        objectName: "considerInputDevices"
                                        text: "Consider input devices"
                                        onClicked: root.settingsDirty = true
                                    }
                                    SelectableLabel {
                                        Layout.fillWidth: true
                                        text: "Use selected input devices to prevent standby. Mouse movement is controlled separately below."
                                    }
                                    SelectableLabel {
                                        Layout.fillWidth: true
                                        text: "Display where mouse movement prevents standby"
                                    }
                                    CopyableComboBox {
                                        id: mouseOutput
                                        objectName: "mouseOutput"
                                        Layout.fillWidth: true
                                        Accessible.name: "Display where mouse movement prevents standby"
                                        property string selectedOutput: ""
                                        readonly property var choices: {
                                            let items = [{path: "", label: "TV display (default)"}]
                                            for (let output of topcec.detectedOutputs)
                                                items.push({path: output.path, label: output.label})
                                            if (selectedOutput.length && !items.some(item => item.path === selectedOutput))
                                                items.push({path: selectedOutput, label: selectedOutput + " (not detected)"})
                                            return items
                                        }
                                        model: choices
                                        textRole: "label"
                                        currentIndex: choices.findIndex(item => item.path === selectedOutput)
                                        onActivated: function(index) {
                                            selectedOutput = choices[index].path
                                            root.settingsDirty = true
                                        }
                                    }
                                    SelectableLabel {
                                        Layout.fillWidth: true
                                        visible: !topcec.detectedOutputs.length
                                        text: topcec.equipmentAvailabilityKnown
                                            ? "No displays detected; the TV display remains available."
                                            : "Display detection unavailable; the TV display remains available."
                                    }
                                }
                            }
                        }
                    }

                    ColumnLayout {
                        objectName: "inputSection"
                        visible: root.currentSection === 3
                        Layout.fillWidth: true
                        Layout.alignment: Qt.AlignTop
                        Layout.minimumWidth: 0
                        Layout.preferredWidth: pageContent.width
                        Layout.maximumWidth: Layout.preferredWidth
                        spacing: Kirigami.Units.smallSpacing
                        RowLayout {
                            Layout.fillWidth: true
                            SelectableHeading {
                                Layout.fillWidth: true
                                level: 3
                                text: "Detected input devices"
                            }
                            SelectableLabel {
                                Layout.maximumWidth: Kirigami.Units.gridUnit * 9
                                Layout.minimumWidth: 0
                                text: root.inputSelectionSummary()
                            }
                        }
                        SurfaceFrame {
                            objectName: "inputFormCard"
                            Layout.fillWidth: true
                            ColumnLayout {
                                width: parent.width
                                spacing: Kirigami.Units.smallSpacing
                                SelectableLabel {
                                    Layout.fillWidth: true
                                    visible: !topcec.detectedInputs.length
                                    text: root.detectedDeviceText(topcec.detectedInputs, false)
                                }
                                Repeater {
                                    id: inputChoices
                                    objectName: "inputChoices"
                                    model: topcec.detectedInputs
                                    delegate: CopyableCheckBox {
                                        required property var modelData
                                        objectName: "inputChoice:" + modelData.path
                                        Layout.fillWidth: true
                                        text: modelData.label + (root.inputAccessBlocked(modelData)
                                            ? " · Access blocked" : "")
                                        checked: root.inputPaths().some(path => path === modelData.path || (modelData.aliases || []).includes(path))
                                        onToggled: root.setInputDeviceSelected(modelData, checked)
                                        onActiveFocusChanged: {
                                            if (activeFocus && settingsPage.flickable) {
                                                let flickable = settingsPage.flickable
                                                let top = mapToItem(flickable.contentItem, 0, 0).y
                                                if (top < flickable.contentY)
                                                    flickable.contentY = top
                                                else if (top + height > flickable.contentY + flickable.height)
                                                    flickable.contentY = top + height - flickable.height
                                            }
                                        }
                                    }
                                }
                            }
                        }
                        SelectableLabel {
                            objectName: "inputSaveHelp"
                            Layout.fillWidth: true
                            text: !topcec.backendAvailable
                                ? (topcec.dbusOnly
                                    ? "Selections remain pending until the host reconnects."
                                    : "Selections remain pending until the host reconnects or you save offline.")
                                : topcec.liveSettingsAvailable
                                    ? "Selections apply automatically without restarting."
                                    : "Selections apply automatically and may restart the service."
                        }
                        SelectableLabel {
                            Layout.fillWidth: true
                            visible: topcec.actionMessage.length > 0
                            text: topcec.actionMessage
                        }
                        CopyableButton {
                            visible: topcec.inputPermissionMessage.length > 0
                            text: "Input access recovery"
                            onClicked: root.openDiagnostics()
                        }
                        DisclosureButton {
                            id: manualPathsToggle
                            objectName: "manualPathsToggle"
                            text: "Manual device paths"
                        }
                        SurfaceFrame {
                            Layout.fillWidth: true
                            visible: manualPathsToggle.checked
                            ColumnLayout {
                                width: parent.width
                                SelectableLabel {
                                    Layout.fillWidth: true
                                    text: "One device path per line"
                                }
                                Controls.ScrollView {
                                    objectName: "devicesScroll"
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 72
                                    clip: true
                                    Controls.ScrollBar.horizontal.policy: Controls.ScrollBar.AlwaysOff
                                    Controls.ScrollBar.vertical.policy: Controls.ScrollBar.AsNeeded
                                    Controls.TextArea {
                                        id: devicesField
                                        objectName: "devicesField"
                                        Accessible.name: "Input device paths (one per line)"
                                        selectByMouse: true
                                        onTextChanged: {
                                            if (activeFocus) root.settingsDirty = true
                                        }
                                        wrapMode: TextEdit.WrapAnywhere
                                    }
                                }
                                CopyableButton {
                                    objectName: "copySelectedInputs"
                                    text: "Copy paths"
                                    enabled: root.inputPaths().length > 0
                                    onClicked: topcec.copyText(root.inputPaths().join("\n"))
                                }
                            }
                        }
                        SelectableLabel {
                            objectName: "retainedInputs"
                            Layout.fillWidth: true
                            visible: root.unresolvedInputs().length > 0
                            text: "Unlisted input paths\n"
                                + root.unresolvedInputs().map(path => root.retainedValue(path)).join("\n")
                        }
                        CopyableButton {
                            objectName: "removeUndetectedInputs"
                            text: "Remove unlisted inputs"
                            visible: root.unresolvedInputs().length > 0
                            onClicked: {
                                devicesField.text = root.inputPaths().filter(path => root.inputDetected(path)).join("\n")
                                root.settingsDirty = true
                            }
                        }
                        DisclosureButton {
                            id: deadzonesToggle
                            text: "Controller deadzones"
                        }
                        SurfaceFrame {
                            Layout.fillWidth: true
                            visible: deadzonesToggle.checked
                            ColumnLayout {
                                width: parent.width
                                SelectableLabel {
                                    Layout.fillWidth: true
                                    visible: root.selectedAxisDevices().some(device => !Array.isArray(device.axes))
                                    text: "Axis information is unavailable for some selected devices. Check discovery diagnostics and update the host backend if needed."
                                }
                                SelectableLabel {
                                    Layout.fillWidth: true
                                    visible: root.selectedAxisRows().length === 0
                                        && !root.selectedAxisDevices().some(device => !Array.isArray(device.axes))
                                    text: "No axes detected on selected input devices."
                                }
                                Repeater {
                                    objectName: "axisChoices"
                                    model: root.selectedAxisRows()
                                    delegate: CopyableFormSpinBox {
                                        required property var modelData
                                        objectName: "axisDeadzone:" + modelData.device.path + ":" + modelData.axis.code
                                        Layout.fillWidth: true
                                        label: modelData.device.label + " · " + modelData.axis.name + " (%)"
                                        from: 1
                                        to: 25
                                        value: Math.round(root.axisValue(modelData.device, modelData.axis))
                                        onValueModified: root.setAxisValue(modelData.device, modelData.axis, value)
                                    }
                                }
                            }
                        }
                    }

                    DisclosureButton {
                        id: firefoxToggle
                        objectName: "firefoxToggle"
                        visible: root.currentSection === 2
                        text: "Firefox mute-tab labels"
                    }
                    SurfaceFrame {
                        Layout.fillWidth: true
                        visible: root.currentSection === 2 && firefoxToggle.checked
                        ColumnLayout {
                            width: parent.width
                            SelectableLabel {
                                Layout.fillWidth: true
                                objectName: "muteLabelsCaption"
                                text: "One label per line"
                            }
                            Controls.TextArea {
                                id: labelsField
                                objectName: "labelsField"
                                Layout.fillWidth: true
                                Layout.preferredHeight: 56
                                Accessible.name: "Firefox mute-tab labels (one per line)"
                                selectByMouse: true
                                onTextChanged: {
                                    if (activeFocus) root.settingsDirty = true
                                }
                            }
                        }
                    }

                    ColumnLayout {
                        id: diagnosticsPanel
                        objectName: "diagnosticsPanel"
                        Layout.fillWidth: true
                        visible: root.onDiagnosticsPage
                        spacing: Kirigami.Units.mediumSpacing

                        FullWidthFrame {
                            Layout.fillWidth: true
                            visible: root.monitoringWarning || topcec.inputPermissionMessage.length > 0
                            ColumnLayout {
                                width: parent.width
                                spacing: Kirigami.Units.smallSpacing
                                Kirigami.InlineMessage {
                                    objectName: "diagnosticsWarningBanner"
                                    Layout.fillWidth: true
                                    visible: root.monitoringWarning
                                    type: Kirigami.MessageType.Warning
                                    text: root.monitoringWarningText
                                }
                                DisclosureButton {
                                    id: inputRecoveryToggle
                                    visible: topcec.inputPermissionMessage.length > 0
                                    text: "Input access recovery"
                                    checked: true
                                }
                                ColumnLayout {
                                    objectName: "inputPermissionHelp"
                                    Layout.fillWidth: true
                                    visible: inputRecoveryToggle.visible && inputRecoveryToggle.checked
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
                                        textFormat: TextEdit.PlainText
                                        wrapMode: TextEdit.WrapAnywhere
                                        font.family: "monospace"
                                    }
                                }
                                Flow {
                                    Layout.fillWidth: true
                                    visible: (inputRecoveryToggle.visible && inputRecoveryToggle.checked
                                        && topcec.inputPermissionCommand.length > 0)
                                        || topcec.monitoringRetryAvailable
                                    spacing: Kirigami.Units.smallSpacing
                                    CopyableButton {
                                        id: copyInputPermissionCommand
                                        objectName: "copyInputPermissionCommand"
                                        visible: inputRecoveryToggle.visible && inputRecoveryToggle.checked
                                            && topcec.inputPermissionCommand.length > 0
                                        text: "Copy command"
                                        icon.name: "edit-copy"
                                        onClicked: topcec.copyText(topcec.inputPermissionCommand)
                                    }
                                    CopyableButton {
                                        id: retryMonitoring
                                        objectName: "retryMonitoringButton"
                                        visible: topcec.monitoringRetryAvailable
                                        enabled: topcec.settingsEnabled
                                        text: "Retry monitoring"
                                        icon.name: "view-refresh"
                                        onClicked: topcec.retryMonitoring()
                                    }
                                }
                            }
                        }
                        SelectableLabel {
                            objectName: "actionDiagnostics"
                            Layout.fillWidth: true
                            visible: topcec.actionMessage.length > 0
                            text: topcec.actionMessage
                        }
                        Flow {
                            objectName: "simulationActions"
                            Layout.fillWidth: true
                            spacing: Kirigami.Units.smallSpacing
                            CopyableButton {
                                objectName: "simulateOnButton"
                                text: "Simulate on"
                                icon.name: "system-shutdown"
                                onClicked: topcec.simulatePower("on")
                            }
                            CopyableButton {
                                objectName: "simulateOffButton"
                                text: "Simulate standby"
                                icon.name: "system-suspend"
                                onClicked: topcec.simulatePower("off")
                            }
                        }
                        FullWidthFrame {
                            Layout.fillWidth: true
                            GridLayout {
                                width: parent.width
                                columns: width >= 330 ? 3 : 1
                                columnSpacing: Kirigami.Units.mediumSpacing
                                DiagnosticState {
                                    label: "Host service"
                                    value: root.hostConnectionStatus
                                    stateColor: topcec.backendAvailable ? Kirigami.Theme.positiveTextColor
                                        : Kirigami.Theme.disabledTextColor
                                }
                                DiagnosticState {
                                    label: "Monitoring"
                                    value: root.monitoringStatus
                                    stateColor: root.serviceHealthy ? Kirigami.Theme.positiveTextColor
                                        : (topcec.backendAvailable ? Kirigami.Theme.neutralTextColor
                                            : Kirigami.Theme.disabledTextColor)
                                }
                                DiagnosticState {
                                    label: "TV power"
                                    value: topcec.powerState.charAt(0).toUpperCase() + topcec.powerState.slice(1)
                                }
                            }
                        }
                        SelectableLabel {
                            objectName: "connectionDiagnostics"
                            Layout.fillWidth: true
                            visible: !topcec.backendAvailable
                            text: topcec.connectionMessage
                        }
                        SelectableLabel {
                            objectName: "standbyDiagnostics"
                            Layout.fillWidth: true
                            visible: topcec.backendAvailable && !root.monitoringWarning
                                && text.length > 0 && text !== topcec.connectionMessage
                            text: topcec.standbyReason
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            SelectableHeading {
                                Layout.fillWidth: true
                                level: 3
                                text: "Detected devices"
                            }
                            CopyableButton {
                                flat: true
                                text: "Open Display"
                                onClicked: root.currentSection = 1
                            }
                        }
                        FullWidthFrame {
                            Layout.fillWidth: true
                            DiagnosticDevice {
                                objectName: "diagnosticsDisplays"
                                label: "TV display"
                                description: root.detectedDeviceText(topcec.detectedOutputs, true)
                            }
                            FormCard.FormDelegateSeparator {}
                            DiagnosticDevice {
                                objectName: "diagnosticsAdapters"
                                label: "CEC adapter"
                                description: root.detectedDeviceText(topcec.detectedAdapters, true)
                            }
                            FormCard.FormDelegateSeparator {}
                            DiagnosticDevice {
                                objectName: "diagnosticsInputs"
                                visible: !topcec.detectedInputs.length
                                label: "Input devices"
                                description: root.detectedDeviceText(topcec.detectedInputs, false)
                            }
                            DisclosureButton {
                                id: diagnosticInputsToggle
                                objectName: "diagnosticInputsToggle"
                                visible: topcec.detectedInputs.length > 0
                                text: "Input devices · " + topcec.detectedInputs.length + " detected · "
                                    + root.inputSelectionSummary()
                            }
                            SelectableLabel {
                                objectName: "diagnosticInputList"
                                Layout.fillWidth: true
                                visible: diagnosticInputsToggle.visible && diagnosticInputsToggle.checked
                                text: root.detectedDeviceText(topcec.detectedInputs, false)
                            }
                            CopyableButton {
                                visible: !diagnosticInputsToggle.visible || diagnosticInputsToggle.checked
                                flat: true
                                text: "Open Input"
                                onClicked: root.currentSection = 3
                            }
                        }
                        SelectableLabel {
                            objectName: "equipmentDiagnostics"
                            Layout.fillWidth: true
                            visible: !topcec.equipmentAvailabilityKnown
                            text: topcec.equipmentMessage
                        }
                        FullWidthFrame {
                            Layout.fillWidth: true
                            DisclosureButton {
                                id: diagnosticDetailsToggle
                                objectName: "diagnosticDetailsToggle"
                                text: "Host service status"
                            }
                            SelectableLabel {
                                objectName: "backendDiagnostics"
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                visible: diagnosticDetailsToggle.checked
                                Accessible.name: "Host service status"
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
            flickable.contentY = 0
        }
    }

    Timer {
        interval: topcec.backendAvailable ? 5000 : 30000
        running: true
        repeat: true
        onTriggered: topcec.refresh()
    }
}
