import QtQuick
import QtQuick.Controls

TabBar {
    id: bar
    property var labels: []
    property int page: 0
    currentIndex: page
    onCurrentIndexChanged: page = currentIndex
    Repeater {
        model: bar.labels
        TabButton { required property string modelData; text: modelData }
    }
}
