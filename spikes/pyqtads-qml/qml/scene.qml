import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Minimal QML surface hosted inside a QtAds dock via QQuickWidget.
// `bridge` is a context property injected from Python; if it survives a
// detach-to-floating + re-dock cycle, the cross-window wiring is intact.
Rectangle {
    color: palette.window

    ColumnLayout {
        anchors.centerIn: parent
        spacing: 12

        Label {
            Layout.alignment: Qt.AlignHCenter
            text: "QML dock (QQuickWidget)"
            font.bold: true
            font.pointSize: 12
        }

        Label {
            Layout.alignment: Qt.AlignHCenter
            text: bridge ? "clicks from Python: " + bridge.click_count : "no bridge!"
            color: bridge ? palette.text : "red"
        }

        Button {
            Layout.alignment: Qt.AlignHCenter
            text: "ping Python"
            onClicked: if (bridge) bridge.ping("hello from QML")
        }

        // A spinning square: continuous rendering is what tends to glitch when
        // the QQuickWidget's backing surface migrates to a floating window.
        Rectangle {
            Layout.alignment: Qt.AlignHCenter
            width: 60; height: 60
            color: palette.highlight
            RotationAnimation on rotation {
                from: 0; to: 360; duration: 2000
                loops: Animation.Infinite; running: true
            }
        }
    }
}
