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
    readonly property var sectionNames: ["Overview", "Equipment", "Automatic standby", "Diagnostics"]
    property bool settingsDirty: false
    property string submittedSettings: ""

    globalDrawer: Kirigami.GlobalDrawer {
        id: navigationDrawer
        objectName: "navigationDrawer"
        title: "topCEC"
        titleIcon: topcec.applicationIcon
        modal: !root.wideScreen
        handleVisible: false
        header: Controls.ToolBar {
            objectName: "appIdentityHeader"
            implicitHeight: pageToolbar.implicitHeight
            leftPadding: Kirigami.Units.largeSpacing
            rightPadding: Kirigami.Units.largeSpacing
            contentItem: RowLayout {
                spacing: Kirigami.Units.smallSpacing
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
                text: "Equipment"
                icon.name: "video-display"
                checked: root.currentSection === 1
                onTriggered: root.currentSection = 1
            },
            Kirigami.Action {
                objectName: "standbyNavigation"
                text: "Automatic standby"
                icon.name: "preferences-system-power-management"
                checked: root.currentSection === 2
                onTriggered: root.currentSection = 2
            },
            Kirigami.Action {
                objectName: "diagnosticsNavigation"
                text: "Diagnostics"
                icon.name: "utilities-log-viewer"
                checked: root.currentSection === 3
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

    function equipmentSummary(selector) {
        if (selector.detected)
            return selector.selectedValue
        if (topcec.configurationSource === "defaults" && !selector.manualEntry)
            return "Not configured"
        return selector.valueToSave.length ? root.retainedValue(selector.valueToSave) : "Not configured"
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
        return root.title + "\n" + settingsPage.title + "\nService: " + root.headerStatus + "\n"
            + root.displayedText(pageContent) + "\n"
            + saveSettingsButton.text + "\n" + settingsSaveStatus.text
    }

    function openDiagnostics() {
        root.currentSection = 3
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

    component DisclosureButton: CopyableButton {
        Layout.fillWidth: true
        flat: true
        checkable: true
        display: Controls.AbstractButton.TextBesideIcon
        icon.name: checked ? "arrow-up" : "arrow-down"
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
                    visible: !root.wideScreen
                    icon.name: "application-menu"
                    text: "Show navigation"
                    display: Controls.AbstractButton.IconOnly
                    onClicked: navigationDrawer.open()
                }
                Kirigami.Heading {
                    Layout.fillWidth: true
                    text: settingsPage.title
                    level: 2
                    elide: Text.ElideRight
                }
                CopyableButton {
                    objectName: "copyPageButton"
                    text: root.width < 500 ? "Copy" : "Copy page text"
                    icon.name: "edit-copy"
                    flat: true
                    Accessible.name: "Copy page text"
                    onClicked: topcec.copyText(root.copyPageText())
                }
            }
        }
        footer: Controls.ToolBar {
            id: applyFooter
            objectName: "applyFooter"
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
            Layout.maximumWidth: 760
            Layout.alignment: Qt.AlignHCenter
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
                        visible: topcec.actionMessage.length > 0
                        text: topcec.actionMessage
                    }

                    ColumnLayout {
                        objectName: "powerCard"
                        Layout.fillWidth: true
                        visible: root.currentSection === 0
                        spacing: Kirigami.Units.largeSpacing
                        RowLayout {
                            Layout.fillWidth: true
                            Layout.topMargin: Kirigami.Units.largeSpacing
                            spacing: Kirigami.Units.largeSpacing
                            Kirigami.Icon {
                                source: "video-display"
                                Layout.preferredWidth: Kirigami.Units.iconSizes.huge
                                Layout.preferredHeight: Kirigami.Units.iconSizes.huge
                                Accessible.ignored: true
                            }
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
                                SelectableLabel {
                                    Layout.fillWidth: true
                                    text: topcec.standbyReason
                                }
                            }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            CopyableButton {
                                objectName: "tvOnButton"
                                text: "Turn on"
                                icon.name: "system-shutdown"
                                enabled: topcec.simulationMode
                                    || (topcec.backendAvailable && topcec.serviceStatus === "running")
                                onClicked: topcec.requestPower("on")
                            }
                            CopyableButton {
                                objectName: "tvStandbyButton"
                                text: "Standby"
                                icon.name: "system-suspend"
                                enabled: topcec.simulationMode
                                    || (topcec.backendAvailable
                                        && topcec.serviceStatus === "running"
                                        && topcec.standbyReason === "Automatic standby allowed")
                                onClicked: topcec.requestPower("off")
                            }
                            Item { Layout.fillWidth: true }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            Kirigami.Icon {
                                source: root.serviceHealthy ? "emblem-success" : "data-warning"
                                color: root.serviceHealthy
                                    ? Kirigami.Theme.positiveTextColor : Kirigami.Theme.neutralTextColor
                                Layout.preferredWidth: Kirigami.Units.iconSizes.small
                                Layout.preferredHeight: Kirigami.Units.iconSizes.small
                                Accessible.ignored: true
                            }
                            SelectableLabel {
                                objectName: "serviceStatusLabel"
                                Layout.fillWidth: true
                                text: root.headerStatus
                                color: root.serviceHealthy
                                    ? Kirigami.Theme.positiveTextColor : Kirigami.Theme.neutralTextColor
                            }
                        }
                    }

                    Kirigami.InlineMessage {
                        objectName: "warningBanner"
                        Layout.fillWidth: true
                        visible: root.currentSection === 0 && topcec.backendAvailable
                            && (topcec.serviceStatus === "configuration-only"
                                || topcec.standbyReason.startsWith("Automatic standby blocked:"))
                        type: Kirigami.MessageType.Warning
                        text: topcec.inputPermissionMessage.length > 0
                            ? "Input access is blocked. Monitoring is inactive."
                            : (topcec.serviceStatus === "configuration-only"
                                ? "Monitoring is inactive."
                                : "Automatic standby is blocked.")
                    }
                    CopyableButton {
                        objectName: "viewRecoverySteps"
                        Layout.alignment: Qt.AlignRight
                        visible: root.currentSection === 0 && topcec.backendAvailable
                            && (topcec.serviceStatus === "configuration-only"
                                || topcec.standbyReason.startsWith("Automatic standby blocked:"))
                        text: "View recovery steps"
                        icon.name: "help-hint"
                        onClicked: root.openDiagnostics()
                    }

                    ColumnLayout {
                        objectName: "overviewSummary"
                        Layout.fillWidth: true
                        visible: root.currentSection === 0
                        spacing: Kirigami.Units.smallSpacing
                        FormCard.FormHeader { title: "Equipment" }
                        FormCard.FormCard {
                            Layout.fillWidth: true
                            FormCard.FormTextDelegate {
                                objectName: "displaySummary"
                                text: "TV display"
                                description: root.equipmentSummary(outputField)
                                leading: Kirigami.Icon {
                                    source: "video-display"
                                    implicitWidth: Kirigami.Units.iconSizes.medium
                                    implicitHeight: Kirigami.Units.iconSizes.medium
                                }
                            }
                            FormCard.FormDelegateSeparator {}
                            FormCard.FormTextDelegate {
                                objectName: "adapterSummary"
                                text: "CEC adapter"
                                description: root.equipmentSummary(adapterField)
                                leading: Kirigami.Icon {
                                    source: "network-wired"
                                    implicitWidth: Kirigami.Units.iconSizes.medium
                                    implicitHeight: Kirigami.Units.iconSizes.medium
                                }
                            }
                            FormCard.FormDelegateSeparator {}
                            CopyableFormButton {
                                objectName: "configureEquipmentButton"
                                text: "Configure equipment…"
                                icon.name: "configure"
                                onClicked: root.currentSection = 1
                            }
                        }
                        FormCard.FormHeader { title: "Automatic standby" }
                        FormCard.FormCard {
                            Layout.fillWidth: true
                            FormCard.FormTextDelegate {
                                text: "Idle timeout"
                                description: timeoutMode.currentIndex === 1
                                    ? timeoutMinutes.value + (timeoutMinutes.value === 1 ? " minute" : " minutes")
                                    : timeoutMode.currentText
                                leading: Kirigami.Icon {
                                    source: "preferences-system-power-management"
                                    implicitWidth: Kirigami.Units.iconSizes.medium
                                    implicitHeight: Kirigami.Units.iconSizes.medium
                                }
                            }
                            FormCard.FormDelegateSeparator {}
                            CopyableFormButton {
                                objectName: "configureStandbyButton"
                                text: "Input devices"
                                description: inputChooserToggle.selectionSummary
                                icon.name: "input-keyboard"
                                onClicked: {
                                    root.currentSection = 2
                                    inputChooserToggle.checked = true
                                }
                            }
                        }
                    }

                    GridLayout {
                        id: configurationGroups
                        objectName: "configurationGroups"
                        Layout.fillWidth: true
                        visible: root.currentSection === 1 || root.currentSection === 2
                        columns: 1
                        columnSpacing: Kirigami.Units.mediumSpacing
                        rowSpacing: Kirigami.Units.mediumSpacing

                        ColumnLayout {
                            objectName: "equipmentSection"
                            visible: root.currentSection === 1
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
                            visible: root.currentSection === 2
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
                        visible: root.currentSection === 0 || root.currentSection === 2
                        text: "Advanced"
                        Accessible.name: "Advanced settings"
                        Accessible.description: checked ? "Expanded" : "Collapsed"
                    }
                    SurfaceFrame {
                        objectName: "advancedPanel"
                        Layout.fillWidth: true
                        visible: advancedToggle.checked
                            && (root.currentSection === 0 || root.currentSection === 2)
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

                    SurfaceFrame {
                        id: diagnosticsPanel
                        objectName: "diagnosticsPanel"
                        Layout.fillWidth: true
                        visible: root.currentSection === 3
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
