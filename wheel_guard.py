"""Wheel navigation must never edit an option/value control, even when focused."""
import atexit
from PyQt6.QtCore import QObject,QEvent,Qt
from PyQt6.QtWidgets import (QApplication,QWidget,QAbstractSpinBox,QComboBox,
                            QAbstractSlider,QScrollBar,QAbstractItemView,QAbstractScrollArea,QTabBar)


class WheelGuard(QObject):
    def eventFilter(self, watched, event):
        if event.type()!=QEvent.Type.Wheel or not isinstance(watched,QWidget):return False
        widget=watched;control=None
        while widget is not None:
            # Open dropdown lists still scroll; choosing a value needs a click.
            if isinstance(widget,QAbstractItemView):return False
            if isinstance(widget,(QAbstractSpinBox,QComboBox,QTabBar)) or (
                    isinstance(widget,QAbstractSlider) and not isinstance(widget,QScrollBar)):
                control=widget;break
            widget=widget.parentWidget()
        if control is None:return False
        parent=control.parentWidget()
        while parent is not None and not isinstance(parent,QAbstractScrollArea):parent=parent.parentWidget()
        if parent is not None:
            pixel=event.pixelDelta();angle=event.angleDelta()
            horizontal=abs(angle.x())>abs(angle.y()) or bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            bar=parent.horizontalScrollBar() if horizontal else parent.verticalScrollBar()
            pixels=(pixel.x() or pixel.y()) if horizontal else pixel.y()
            units=(angle.x() or angle.y()) if horizontal else angle.y()
            distance=pixels if pixels else units/120*bar.singleStep()*QApplication.wheelScrollLines()
            # Send no nested wheel event: Qt may retarget it back to the focused
            # editor. Moving only the enclosing scrollbar cannot edit a value.
            bar.setValue(bar.value()-round(distance))
        event.accept()
        return True


def install_wheel_guard():
    app=QApplication.instance()
    if app is not None and not hasattr(app,'_option_wheel_guard'):
        app._option_wheel_guard=WheelGuard(app)
        app.installEventFilter(app._option_wheel_guard)
        # Remove the Python filter before QApplication/native widgets tear down.
        # Keep the application alive through headless test runs as well.
        def cleanup(application=app,guard=app._option_wheel_guard):
            try:application.removeEventFilter(guard)
            except RuntimeError:pass
        app.aboutToQuit.connect(cleanup)
        atexit.register(cleanup)
