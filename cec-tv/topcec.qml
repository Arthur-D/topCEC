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
    property var mouseOutputsDraft: []
    property bool mouseOutputsLegacy: false
    property bool mouseOutputsFollowTarget: false
    property var idleAppsDraft: []
    property var forceAppsDraft: []
    property var retainedAppIds: []
    property bool firefoxAudioEnabled: false
    property var chromiumAudioDraft: []
    property bool firefoxVideoEnabled: false
    property var chromiumVideoDraft: []
    property real defaultAxisDeadzone: 0
    property real defaultRzDeadzone: 0
    onSettingsDirtyChanged: {
        if (settingsDirty)
            autoSaveTimer.restart()
    }

    Timer {
        id: autoSaveTimer
        objectName: "autoSaveTimer"
        interval: 300
        onTriggered: root.applySettings()
    }

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
            mouseOutputs: mouseOutputsLegacy ? null : mouseOutputsDraft,
            muteLabels: labelsField.text,
            firefoxAudioBlocksStandby: firefoxAudioEnabled,
            chromiumAudioBlocksStandby: chromiumAudioDraft,
            firefoxVideoBlocksStandby: firefoxVideoEnabled,
            chromiumVideoBlocksStandby: chromiumVideoDraft,
            idleInhibitionApps: idleAppsDraft,
            forceInhibitionApps: forceAppsDraft,
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

    readonly property bool equipmentReady: !adapterField.valueToSave.trim().length
        || (outputField.acceptable && adapterField.acceptable)

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
        root.markSettingsDirty()
    }

    function markSettingsDirty() {
        settingsDirty = true
        autoSaveTimer.restart()
    }

    function scheduleAutoSave() {
        autoSaveTimer.restart()
    }

    function applySettings() {
        if (!settingsDirty || !topcec.settingsEnabled || !equipmentReady)
            return
        let values = settingsValues()
        submittedSettings = JSON.stringify(values)
        values.targetOutput = outputField.valueToSave
        values.adapter = adapterField.valueToSave
        values.devices = savedInputPaths()
        topcec.applySettings(values)
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
    readonly property bool cecAdapterSelected: adapterField.detected
    function powerStateText() {
        if (topcec.serviceStatus === "configuration-only"
                && topcec.powerState === "unknown")
            return "No CEC-enabled TV detected"
        if (root.serviceHealthy) {
            if (!root.cecAdapterSelected)
                return adapterField.availabilityKnown
                    ? "No CEC adapter selected" : "CEC adapter detection unavailable"
            if (!outputField.detected) {
                if (!outputField.availabilityKnown)
                    return "Display detection unavailable"
                return outputField.equipment.length
                    ? "No display selected" : "No display detected"
            }
        }
        return topcec.powerState.replace(/_/g, " ")
    }
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
        if (!root.equipmentReady)
            return "Choose a display and CEC adapter."
        if (root.settingsDirty)
            return "Saving changes..."
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
            + (applyFooter.visible ? settingsSaveStatus.text : "")
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
                    && !selection.length) {
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
            root.markSettingsDirty()
        }
        onEditTextChanged: {
            if (!syncing && manualEntry) {
                automaticSelection = false
                explicitSelection = true
                selectedValue = editText
                if (activeFocus)
                    root.markSettingsDirty()
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
        considerInputDevices.checked = topcec.setting("consider_input_devices")
        let outputs = topcec.setting("mouse_outputs")
        mouseOutputsLegacy = outputs === null || outputs === undefined
        mouseOutputsFollowTarget = mouseOutputsLegacy && !topcec.setting("mouse_output")
        mouseOutputsDraft = mouseOutputsLegacy
            ? [topcec.setting("mouse_output") || topcec.setting("target_output")]
            : Array.from(outputs)
        devicesField.text = topcec.deviceList()
        labelsField.text = topcec.muteLabelList()
        firefoxAudioEnabled = topcec.setting("firefox_audio_blocks_standby")
        chromiumAudioDraft = Array.from(topcec.setting("chromium_audio_blocks_standby") || [])
        firefoxVideoEnabled = topcec.setting("firefox_video_blocks_standby") || false
        chromiumVideoDraft = Array.from(topcec.setting("chromium_video_blocks_standby") || [])
        idleAppsDraft = Array.from(topcec.setting("idle_inhibition_apps") || [])
        forceAppsDraft = Array.from(topcec.setting("force_inhibition_apps") || [])
        retainedAppIds = [...new Set([...idleAppsDraft, ...forceAppsDraft])]
        defaultAxisDeadzone = topcec.setting("axis_deadzone_percent")
        defaultRzDeadzone = topcec.setting("rz_deadzone_percent")
        axisDraft = JSON.parse(JSON.stringify(topcec.setting("device_axis_deadzones") || {}))
    }

    function isFirefoxApp(id) {
        let key = id.toLowerCase().replace(/\.desktop$/, "")
        return ["firefox", "firefox-esr", "firefox_firefox", "org.mozilla.firefox",
                "org.mozilla.firefoxdeveloperedition", "org.mozilla.firefox-beta"].includes(key)
    }

    property var chromiumBrowsers: [
        {id: "chromium", name: "Chromium", extensionsUrl: "chrome://extensions", aliases: ["chromium", "chromium-browser", "org.chromium.chromium"]},
        {id: "chrome", name: "Google Chrome", extensionsUrl: "chrome://extensions", aliases: ["google-chrome", "google-chrome-stable", "com.google.chrome"]},
        {id: "brave", name: "Brave", extensionsUrl: "brave://extensions", aliases: ["brave", "brave-browser", "brave-browser-stable", "com.brave.browser"]},
        {id: "edge", name: "Microsoft Edge", extensionsUrl: "edge://extensions", aliases: ["msedge", "microsoft-edge", "microsoft-edge-stable", "com.microsoft.edge"]},
        {id: "vivaldi", name: "Vivaldi", extensionsUrl: "vivaldi://extensions", aliases: ["vivaldi", "vivaldi-bin", "vivaldi-stable", "com.vivaldi.vivaldi"]}
    ]
    readonly property var setupBrowsers: chromiumBrowsers.concat([
        {id: "firefox", name: "Mozilla Firefox", isFirefox: true}
    ])

    function browserForApp(app) {
        let keys = [app.id || "", app.window_class || ""].map(
            value => value.toLowerCase().replace(/\.desktop$/, ""))
        for (let browser of chromiumBrowsers) {
            if (keys.some(key => browser.aliases.includes(key)))
                return browser
        }
        let path = keys[0]
        if (path.startsWith("/")) {
            let executable = path.substring(path.lastIndexOf("/") + 1)
            for (let browser of chromiumBrowsers) {
                if (browser.aliases.includes(executable))
                    return browser
            }
        }
        if (path.startsWith("/") && path.endsWith("/chrome")) {
            if (path.includes("/chromium/")) return chromiumBrowsers[0]
            if (path === "/app/extra/chrome" || path.includes("/google/chrome/"))
                return chromiumBrowsers[1]
        }
        return null
    }

    function browserApp(browserId) {
        return topcec.observedApps.find(app => root.browserForApp(app)?.id === browserId)
            || topcec.installedApps.find(app => root.browserForApp(app)?.id === browserId)
            || null
    }

    function browserIsInstalled(app, installedBrowserIds, firefoxInstalled) {
        let browser = browserForApp(app)
        return browser ? installedBrowserIds.has(browser.id)
            : !isFirefoxApp(app.id) || firefoxInstalled
    }

    function setChromiumAudio(browserId, enabled) {
        let choices = chromiumAudioDraft.filter(id => id !== browserId)
        if (enabled)
            choices.push(browserId)
        chromiumAudioDraft = choices
    }

    function appChoices() {
        let installedApps = topcec.installedApps
        let installedBrowserIds = new Set(installedApps.map(app => browserForApp(app)?.id)
            .filter(Boolean))
        let firefox = installedApps.find(app => isFirefoxApp(app.id)) || null
        let apps = topcec.observedApps.filter(app =>
            browserIsInstalled(app, installedBrowserIds, !!firefox))
        let launcherGroups = new Set(apps.map(app => app.launcher_group).filter(Boolean))
        for (let app of installedApps) {
            if (app.launcher_group && retainedAppIds.includes(app.id))
                launcherGroups.add(app.launcher_group)
        }
        if (firefox && !apps.some(app => app.id === firefox.id))
            apps.push(firefox)
        for (let app of installedApps) {
            if (!app.menu_hidden
                    && (showAllApps.checked || browserForApp(app) || isFirefoxApp(app.id)
                    || launcherGroups.has(app.launcher_group))
                    && !apps.some(item => item.id === app.id))
                apps.push(app)
        }
        for (let id of retainedAppIds) {
            if (!apps.some(app => app.id === id)) {
                let installed = installedApps.find(app => app.id === id)
                let app = installed || {id: id, name: id + " (not installed)"}
                if (browserIsInstalled(app, installedBrowserIds, !!firefox))
                    apps.push(app)
            }
        }
        let query = appSearch.text.trim().toLowerCase()
        if (query && !showAllApps.checked) {
            for (let id of topcec.activeInhibitorApps) {
                if (!apps.some(app => app.id === id)) {
                    let installed = installedApps.find(app => app.id === id)
                    let app = installed || {id: id, name: id}
                    if (browserIsInstalled(app, installedBrowserIds, !!firefox))
                        apps.push(app)
                }
            }
        }
        let grouped = []
        for (let app of apps) {
            let browser = browserForApp(app)
            let browserId = app.browserId || browser?.id || ""
            let firefoxMatch = isFirefoxApp(app.id)
            let key = browserId ? "browser:" + browserId : firefoxMatch ? "firefox"
                : "app:" + (app.launcher_group || app.id)
            let existing = grouped.find(item => item.groupKey === key)
            if (existing) {
                if (!existing.groupIds.includes(app.id))
                    existing.groupIds.push(app.id)
                continue
            }
            let primary = browserId ? browserApp(browserId) : (firefoxMatch ? firefox : null)
            grouped.push({id: primary?.id || app.id,
                          name: browserId ? chromiumBrowsers.find(item => item.id === browserId).name
                              : (firefoxMatch ? primary.name : app.name),
                          groupIds: [app.id], browserId: browserId,
                          isFirefox: firefoxMatch, groupKey: key})
        }
        return grouped.filter(app => !query || ((showAllApps.checked
            || app.groupIds.some(id => topcec.activeInhibitorApps.includes(id)))
            && (app.name + " " + app.groupIds.join(" ")).toLowerCase().includes(query)))
            .sort((a, b) => Number(b.groupIds.some(id => topcec.activeInhibitorApps.includes(id)))
                - Number(a.groupIds.some(id => topcec.activeInhibitorApps.includes(id)))
                || a.name.localeCompare(b.name))
    }

    function selectedMouseDisplays() {
        return mouseOutputsFollowTarget
            ? [outputField.valueToSave || topcec.setting("target_output")].filter(path => path.length)
            : mouseOutputsDraft
    }

    function mouseDisplayChoices() {
        let choices = topcec.detectedOutputs.slice()
        for (let path of selectedMouseDisplays()) {
            if (!choices.some(item => item.path === path))
                choices.push({path: path, label: root.retainedValue(path)})
        }
        return choices
    }

    function setMouseDisplay(path, enabled) {
        let selected = selectedMouseDisplays()
        mouseOutputsLegacy = false
        mouseOutputsFollowTarget = false
        mouseOutputsDraft = enabled ? [...selected.filter(item => item !== path), path]
            : selected.filter(item => item !== path)
        root.markSettingsDirty()
    }

    function setIdleApp(id, enabled) {
        idleAppsDraft = enabled ? [...idleAppsDraft.filter(item => item !== id), id]
            : idleAppsDraft.filter(item => item !== id)
        root.markSettingsDirty()
    }

    function setForceApp(id, enabled) {
        forceAppsDraft = enabled ? [...forceAppsDraft.filter(item => item !== id), id]
            : forceAppsDraft.filter(item => item !== id)
        root.markSettingsDirty()
    }

    function setAppGroup(ids, enabled, force) {
        let current = force ? forceAppsDraft : idleAppsDraft
        let updated = current.filter(id => !ids.includes(id))
        if (enabled)
            updated.push(...ids)
        if (force)
            forceAppsDraft = updated
        else
            idleAppsDraft = updated
        root.markSettingsDirty()
    }

    Component.onCompleted: loadSettings()
    Connections {
        target: topcec
        function onAppsChanged() {
            root.retainedAppIds = [...new Set([...root.retainedAppIds, ...root.idleAppsDraft, ...root.forceAppsDraft])]
        }
        function onConfigurationChanged() { root.loadSettings() }
        function onSettingsEnabledChanged() {
            if (root.settingsDirty)
                root.scheduleAutoSave()
        }
        function onSettingsSaved() {
            if (root.submittedSettings && JSON.stringify(root.settingsValues()) !== root.submittedSettings)
                return
            root.settingsDirty = false
            root.loadSettings()
        }
    }
    Connections {
        target: root
        function onEquipmentReadyChanged() {
            if (root.settingsDirty)
                root.scheduleAutoSave()
        }
    }

    component SurfaceFrame: FormCard.FormCard {
        padding: Kirigami.Units.smallSpacing
        maximumWidth: width
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
            Layout.maximumWidth: Kirigami.Units.gridUnit * 60
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
                            text: "3. Start the host service. CEC stays off until you configure a TV display and adapter:"
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
                            text: "4. Return here to configure your display and adapter. Use Retry Connection if needed."
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
                                RowLayout {
                                    objectName: "monitoringStatusRow"
                                    Layout.fillWidth: true
                                    spacing: Kirigami.Units.smallSpacing
                                    SelectableLabel {
                                        objectName: "serviceStatusLabel"
                                        Layout.minimumWidth: implicitWidth
                                        wrapMode: TextEdit.NoWrap
                                        text: root.headerStatus + ","
                                        color: root.serviceHealthy
                                            ? Kirigami.Theme.positiveTextColor : Kirigami.Theme.textColor
                                    }
                                    SelectableLabel {
                                        objectName: "powerStateLabel"
                                        Layout.fillWidth: true
                                        font.bold: true
                                        text: root.powerStateText()
                                    }
                                }
                            }
                            RowLayout {
                                CopyableButton {
                                    objectName: "tvOnButton"
                                    text: "Turn on"
                                    icon.name: "system-shutdown"
                                    enabled: root.serviceHealthy && root.cecAdapterSelected
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
                                        onToggled: root.markSettingsDirty()
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
                                        onToggled: root.markSettingsDirty()
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
                                            objectName: "idleTimeoutLabel"
                                            text: "Idle timeout"
                                            wrapMode: TextEdit.NoWrap
                                            Layout.minimumWidth: implicitWidth
                                        }
                                        CopyableComboBox {
                                            id: timeoutMode
                                            objectName: "timeoutMode"
                                            Layout.fillWidth: true
                                            Accessible.name: "Idle timeout"
                                            model: [topcec.plasmaTimeoutLabel, "Custom", "Disabled"]
                                            onActivated: root.markSettingsDirty()
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
                                            onValueModified: root.markSettingsDirty()
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
                                        onClicked: root.markSettingsDirty()
                                    }
                                    SelectableLabel {
                                        Layout.fillWidth: true
                                        text: "Use selected input devices to prevent standby. Mouse movement is controlled separately below."
                                    }
                                    SelectableLabel {
                                        Layout.fillWidth: true
                                        text: "Displays where mouse movement prevents standby"
                                    }
                                    Repeater {
                                        objectName: "mouseDisplayChoices"
                                        model: root.mouseDisplayChoices()
                                        delegate: CopyableCheckBox {
                                            required property var modelData
                                            objectName: "mouseDisplay:" + modelData.path
                                            Layout.fillWidth: true
                                            text: modelData.label
                                            checked: root.selectedMouseDisplays().includes(modelData.path)
                                            onClicked: root.setMouseDisplay(modelData.path, checked)
                                        }
                                    }
                                    SelectableLabel {
                                        Layout.fillWidth: true
                                        visible: !topcec.detectedOutputs.length
                                        text: topcec.equipmentAvailabilityKnown
                                            ? "No displays detected. Saved selections are retained."
                                            : "Display detection unavailable. Saved selections are retained."
                                    }
                                    SelectableLabel {
                                        Layout.fillWidth: true
                                        text: "App activity can also prevent standby on selected displays."
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
                            visible: topcec.dbusOnly && !topcec.backendAvailable
                            text: "Selections remain pending until the host reconnects."
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
                                            if (activeFocus) root.markSettingsDirty()
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
                                root.markSettingsDirty()
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
                                    visible: root.selectedAxisRows().length === 0
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
                                        from: 0
                                        to: 25
                                        value: Math.round(root.axisValue(modelData.device, modelData.axis))
                                        onValueModified: root.setAxisValue(modelData.device, modelData.axis, value)
                                    }
                                }
                            }
                        }
                    }

                    SelectableHeading {
                        visible: root.currentSection === 2
                        level: 3
                        text: "Apps"
                    }
                    SelectableHeading {
                        visible: root.currentSection === 2
                        objectName: "canBlockStandbyHeading"
                        level: 4
                        text: "Can block screen standby"
                    }
                    SurfaceFrame {
                        Layout.fillWidth: true
                        visible: root.currentSection === 2
                        ColumnLayout {
                            width: parent.width
                            SelectableLabel {
                                Layout.fillWidth: true
                                text: "Turn off Allow standby to follow an app's Plasma request. Force block standby blocks TV standby while the app has a window on a selected display. Neither option prevents computer sleep."
                            }
                            CopyableCheckBox {
                                id: showAllApps
                                objectName: "showAllApps"
                                text: "Show all installed apps"
                                onClicked: {
                                    if (!checked)
                                        root.retainedAppIds = [...new Set([...root.retainedAppIds,
                                            ...root.idleAppsDraft, ...root.forceAppsDraft])]
                                }
                            }
                            Controls.TextField {
                                id: appSearch
                                objectName: "appSearch"
                                Layout.fillWidth: true
                                placeholderText: showAllApps.checked ? "Search all installed apps"
                                    : "Search apps currently requesting screen inhibition"
                                Accessible.name: placeholderText
                            }
                            SelectableLabel {
                                Layout.fillWidth: true
                                visible: topcec.appDiscoveryMessage.length > 0
                                text: topcec.appDiscoveryMessage
                            }
                            SelectableLabel {
                                Layout.fillWidth: true
                                visible: topcec.inhibitionHistoryMessage.length > 0
                                text: topcec.inhibitionHistoryMessage
                            }
                            SelectableLabel {
                                Layout.fillWidth: true
                                visible: root.appChoices().length === 0
                                text: appSearch.text.trim().length > 0
                                    ? (showAllApps.checked ? "No installed apps match this search."
                                        : "No apps currently requesting screen inhibition match this search.")
                                    : "No apps have requested idle inhibition yet. Show all installed apps to choose one."
                            }
                            ListView {
                                id: appList
                                objectName: "installedAppsScroll"
                                Layout.fillWidth: true
                                Layout.preferredHeight: Math.min(300, Math.max(40, contentHeight))
                                visible: count > 0
                                clip: true
                                model: root.appChoices()
                                Controls.ScrollBar.vertical: Controls.ScrollBar { id: appScrollBar }
                                delegate: GridLayout {
                                    id: appRow
                                    required property var modelData
                                    objectName: "appRow:" + modelData.id
                                    width: appList.width - appScrollBar.implicitWidth
                                    columnSpacing: Kirigami.Units.smallSpacing
                                    rowSpacing: 0
                                    readonly property real policyWidth: allowStandby.implicitWidth
                                        + forceStandby.implicitWidth + columnSpacing
                                    readonly property real minimumNameWidth: Kirigami.Units.gridUnit * 6
                                    readonly property real policyRowWidth: policyWidth + columnSpacing
                                    readonly property bool stackName: width < minimumNameWidth + policyRowWidth
                                    readonly property bool stackPolicies: width < policyWidth
                                    readonly property bool browserAudio: modelData.browserId.length > 0
                                    readonly property real nameWidth: stackName ? width
                                        : Math.min(Kirigami.Units.gridUnit * 10,
                                            width - policyRowWidth)

                                    SelectableLabel {
                                        objectName: "appName:" + modelData.id
                                        Layout.row: 0
                                        Layout.column: 0
                                        Layout.columnSpan: appRow.stackName ? 4 : 1
                                        Layout.minimumWidth: appRow.nameWidth
                                        Layout.preferredWidth: appRow.nameWidth
                                        Layout.maximumWidth: appRow.nameWidth
                                        Layout.alignment: Qt.AlignTop | Qt.AlignLeft
                                        text: modelData.name
                                        topPadding: Kirigami.Units.smallSpacing
                                    }
                                    CopyableCheckBox {
                                        id: allowStandby
                                        objectName: "idleApp:" + modelData.id
                                        Layout.row: appRow.stackName ? 1 : 0
                                        Layout.column: appRow.stackName ? 0 : 1
                                        Layout.maximumWidth: implicitWidth
                                        Layout.alignment: Qt.AlignTop | Qt.AlignLeft
                                        text: "Allow standby"
                                        Accessible.name: modelData.name + " allow standby"
                                        checked: !modelData.groupIds.some(id => root.idleAppsDraft.includes(id))
                                        onClicked: root.setAppGroup(modelData.groupIds, !checked, false)
                                    }
                                    CopyableCheckBox {
                                        id: forceStandby
                                        objectName: "forceApp:" + modelData.id
                                        Layout.row: appRow.stackPolicies ? 2 : (appRow.stackName ? 1 : 0)
                                        Layout.column: appRow.stackPolicies ? 0 : (appRow.stackName ? 1 : 2)
                                        Layout.maximumWidth: implicitWidth
                                        Layout.alignment: Qt.AlignTop | Qt.AlignLeft
                                        text: "Force block standby"
                                        Accessible.name: modelData.name + " force block standby"
                                        checked: modelData.groupIds.some(id => root.forceAppsDraft.includes(id))
                                        onClicked: root.setAppGroup(modelData.groupIds, checked, true)
                                    }
                                    Flow {
                                        objectName: "browserMediaOptions:" + modelData.id
                                        Layout.row: appRow.stackPolicies ? 3 : 2
                                        Layout.column: 0
                                        Layout.columnSpan: 4
                                        Layout.fillWidth: true
                                        spacing: Kirigami.Units.smallSpacing
                                        CopyableCheckBox {
                                            id: browserAudioControl
                                            objectName: modelData.isFirefox ? "firefoxAudio"
                                                : (appRow.browserAudio ? "browserAudio:" + modelData.browserId : "")
                                            visible: modelData.isFirefox || appRow.browserAudio
                                            text: "Block standby while playing audio"
                                            Accessible.name: modelData.name + " block standby while playing audio"
                                            checked: appRow.browserAudio
                                                ? root.chromiumAudioDraft.includes(modelData.browserId)
                                                : root.firefoxAudioEnabled
                                            onClicked: {
                                                if (appRow.browserAudio)
                                                    root.setChromiumAudio(modelData.browserId, checked)
                                                else
                                                    root.firefoxAudioEnabled = checked
                                                root.markSettingsDirty()
                                            }
                                        }
                                        CopyableCheckBox {
                                            id: browserVideoControl
                                            objectName: modelData.isFirefox ? "firefoxVideo"
                                                : (appRow.browserAudio ? "browserVideo:" + modelData.browserId : "")
                                            visible: modelData.isFirefox || appRow.browserAudio
                                            text: "Block standby while playing video"
                                            Accessible.name: modelData.name + " block standby while playing video"
                                            checked: appRow.browserAudio
                                                ? root.chromiumVideoDraft.includes(modelData.browserId)
                                                : root.firefoxVideoEnabled
                                            onClicked: {
                                                if (appRow.browserAudio) {
                                                    let choices = root.chromiumVideoDraft.filter(id => id !== modelData.browserId)
                                                    if (checked) choices.push(modelData.browserId)
                                                    root.chromiumVideoDraft = choices
                                                } else {
                                                    root.firefoxVideoEnabled = checked
                                                }
                                                root.markSettingsDirty()
                                            }
                                        }
                                    }
                                    Item {
                                        visible: !appRow.stackName
                                        Layout.row: 0
                                        Layout.column: 4
                                        Layout.fillWidth: true
                                    }
                                }
                            }
                        }
                    }
                    DisclosureButton {
                        id: browserSetupToggle
                        objectName: "browserSetupToggle"
                        visible: root.currentSection === 2
                        text: "Set up a browser extension"
                    }
                    SurfaceFrame {
                        Layout.fillWidth: true
                        visible: root.currentSection === 2 && browserSetupToggle.checked
                        ColumnLayout {
                            width: parent.width
                            SelectableLabel {
                                Layout.fillWidth: true
                                text: "Choose your browser and installation type. Firefox uses an optional add-on."
                            }
                            Flow {
                                Layout.fillWidth: true
                                spacing: Kirigami.Units.smallSpacing
                                Controls.ComboBox {
                                    id: setupBrowser
                                    objectName: "setupBrowser"
                                    model: root.setupBrowsers
                                    textRole: "name"
                                    currentIndex: -1
                                    displayText: currentIndex < 0 ? "Select browser" : currentText
                                    implicitWidth: Math.max(implicitContentWidth,
                                        contentItem.implicitWidth) + leftPadding + rightPadding
                                        + indicator.width + spacing
                                    enabled: !topcec.browserSetupPending
                                    Accessible.name: "Browser"
                                    onCurrentIndexChanged: {
                                        setupExtensionId.text = ""
                                        setupGrantAccess.checked = false
                                        topcec.resetBrowserSetup()
                                    }
                                }
                                Controls.ComboBox {
                                    id: setupInstallation
                                    objectName: "setupInstallation"
                                    model: ["Flatpak", "Native"]
                                    currentIndex: -1
                                    displayText: currentIndex < 0 ? "Installation type" : currentText
                                    implicitWidth: Math.max(implicitContentWidth,
                                        contentItem.implicitWidth) + leftPadding + rightPadding
                                        + indicator.width + spacing
                                    enabled: !topcec.browserSetupPending
                                    Accessible.name: "Browser installation type"
                                    onCurrentIndexChanged: {
                                        setupExtensionId.text = ""
                                        setupGrantAccess.checked = false
                                        topcec.resetBrowserSetup()
                                    }
                                }
                                Controls.Button {
                                    objectName: "prepareBrowserExtension"
                                    text: "Prepare extension"
                                    enabled: setupBrowser.currentIndex >= 0
                                        && setupInstallation.currentIndex >= 0
                                        && !topcec.browserSetupPending
                                    onClicked: topcec.setupBrowser(
                                        root.setupBrowsers[setupBrowser.currentIndex].id,
                                        setupInstallation.currentIndex === 0, "", false)
                                }
                            }
                            SelectableLabel {
                                objectName: "browserSetupMessage"
                                Layout.fillWidth: true
                                visible: topcec.browserSetupMessage.length > 0
                                text: topcec.browserSetupMessage
                            }
                            SelectableLabel {
                                objectName: "browserSetupInstructions"
                                Layout.fillWidth: true
                                visible: topcec.browserSetupPath.length > 0
                                text: {
                                    if (setupBrowser.currentIndex < 0)
                                        return ""
                                    let browser = root.setupBrowsers[setupBrowser.currentIndex]
                                    if (browser.isFirefox)
                                        return "In Firefox 140 or newer, open "
                                            + "about:debugging#/runtime/this-firefox, choose "
                                            + "Load Temporary Add-on, and select manifest.json "
                                            + "from this folder:"
                                    return "Open " + browser.extensionsUrl
                                        + " in your browser, enable Developer mode, and load "
                                        + "unpacked from this folder:"
                                }
                            }
                            SelectableLabel {
                                objectName: "browserSetupPath"
                                Layout.fillWidth: true
                                visible: topcec.browserSetupPath.length > 0
                                text: topcec.browserSetupPath
                            }
                            Controls.Button {
                                objectName: "copyBrowserSetupPath"
                                visible: topcec.browserSetupPath.length > 0
                                text: "Copy folder path"
                                icon.name: "edit-copy"
                                onClicked: topcec.copyText(topcec.browserSetupPath)
                            }
                            Controls.TextField {
                                id: setupExtensionId
                                objectName: "browserExtensionId"
                                Layout.fillWidth: true
                                visible: topcec.browserSetupPath.length > 0
                                    && setupBrowser.currentIndex >= 0
                                    && !root.setupBrowsers[setupBrowser.currentIndex].isFirefox
                                placeholderText: "Paste the 32-letter extension ID shown by the browser"
                                Accessible.name: "Browser extension ID"
                                enabled: !topcec.browserSetupPending
                            }
                            CopyableCheckBox {
                                id: setupGrantAccess
                                objectName: "browserGrantAccess"
                                visible: topcec.browserSetupPath.length > 0
                                    && setupBrowser.currentIndex >= 0
                                    && !root.setupBrowsers[setupBrowser.currentIndex].isFirefox
                                    && setupInstallation.currentIndex === 0
                                enabled: !topcec.browserSetupPending
                                text: "Allow this Flatpak browser to send media status to topCEC"
                            }
                            Controls.Button {
                                objectName: "registerBrowserExtension"
                                visible: topcec.browserSetupPath.length > 0
                                    && setupBrowser.currentIndex >= 0
                                    && !root.setupBrowsers[setupBrowser.currentIndex].isFirefox
                                text: "Register native host"
                                enabled: !topcec.browserSetupPending
                                    && /^[a-p]{32}$/.test(setupExtensionId.text.trim())
                                onClicked: topcec.setupBrowser(
                                    root.setupBrowsers[setupBrowser.currentIndex].id,
                                    setupInstallation.currentIndex === 0,
                                    setupExtensionId.text.trim(), setupGrantAccess.checked)
                            }
                        }
                    }
                    DisclosureButton {
                        id: firefoxToggle
                        objectName: "firefoxToggle"
                        visible: root.currentSection === 2
                        text: "Mute tab labels"
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
                                    if (activeFocus) root.markSettingsDirty()
                                }
                            }
                        }
                    }

                    SelectableHeading {
                        visible: root.currentSection === 2
                        level: 4
                        text: "Currently blocking standby"
                    }
                    SelectableLabel {
                        objectName: "appBlockingStatus"
                        Layout.fillWidth: true
                        visible: root.currentSection === 2 && topcec.firefoxPlaybackActive
                        text: "Firefox · Audio"
                    }
                    SelectableLabel {
                        objectName: "firefoxAudioStatus"
                        Layout.fillWidth: true
                        visible: root.currentSection === 2 && root.firefoxAudioEnabled
                            && topcec.firefoxAudioStatusMessage.length > 0
                        text: topcec.firefoxAudioStatusMessage
                    }
                    SelectableLabel {
                        objectName: "chromiumAudioStatus"
                        Layout.fillWidth: true
                        visible: root.currentSection === 2 && topcec.chromiumAudioStatusMessage.length > 0
                        text: topcec.chromiumAudioStatusMessage
                    }
                    SelectableLabel {
                        Layout.fillWidth: true
                        visible: root.currentSection === 2 && topcec.inhibitionsMessage.length > 0
                        text: topcec.inhibitionsMessage
                    }
                    SelectableLabel {
                        objectName: "noBlockingApps"
                        Layout.fillWidth: true
                        visible: root.currentSection === 2 && !topcec.firefoxPlaybackActive
                            && (!root.firefoxAudioEnabled || topcec.firefoxAudioStatusMessage.length === 0)
                            && topcec.chromiumAudioStatusMessage.length === 0
                            && topcec.blockingApps.length === 0 && topcec.inhibitionsMessage.length === 0
                        text: "No apps are currently blocking standby."
                    }
                    Repeater {
                        model: root.currentSection === 2 ? topcec.blockingApps : []
                        delegate: SelectableLabel {
                            required property var modelData
                            Layout.fillWidth: true
                            text: modelData.app + " · " + (modelData.reason || "Blocking screen standby")
                                + (modelData.identityUnknown ? " (app identity unknown)"
                                    : (modelData.locationUnknown ? " (display unknown)" : ""))
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
                        SelectableLabel {
                            objectName: "firefoxAccessibilityHelp"
                            Layout.fillWidth: true
                            visible: topcec.firefoxAccessibilityHelp.length > 0
                            text: topcec.firefoxAccessibilityHelp
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
