import QtQuick
import QtQuick.Controls.Basic as Basic
import QtQuick.NativeStyle as NativeStyle
import ".."

// Keep the AppKit stepper; match the adjoining field to the other form fields.
Basic.SpinBox {
    id: control
    implicitWidth: 132
    implicitHeight: 30
    leftPadding: 0
    topPadding: 0
    bottomPadding: 0
    rightPadding: stepper.width + 6
    background: Item { }
    contentItem: DialogTextField {
        text: control.displayText
        font: control.font
        readOnly: !control.editable
        validator: control.validator
        inputMethodHints: control.inputMethodHints
    }
    NativeStyle.SpinBox {
        id: stepper
        control: control
        subControl: NativeStyle.SpinBox.Up
        x: control.width - width
        y: (control.height - height) / 2
        useNinePatchImage: false
    }
    up.indicator: Item {
        x: control.width - width
        y: (control.height - stepper.height) / 2
        implicitWidth: stepper.width
        implicitHeight: stepper.height / 2
    }
    down.indicator: Item {
        x: control.width - width
        y: (control.height + stepper.height) / 2 - height
        implicitWidth: stepper.width
        implicitHeight: stepper.height / 2
    }
}
