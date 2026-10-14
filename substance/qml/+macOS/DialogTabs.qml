import QtQuick
import ".."

SegmentedSelector {
    property int page: 0
    selectedIndex: page
    onActivated: index => page = index
}
