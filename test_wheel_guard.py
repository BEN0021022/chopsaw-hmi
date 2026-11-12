"""Wheel cannot alter focused, unfocused, nested or newly-created controls."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PyQt6.QtCore import QPoint,QPointF,Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import (QApplication,QWidget,QVBoxLayout,QDoubleSpinBox,QSpinBox,
                            QComboBox,QScrollArea,QLineEdit,QSlider,QTabBar,QDateTimeEdit)
from PyQt6.QtTest import QTest
from wheel_guard import install_wheel_guard


def run():
    app=QApplication.instance() or QApplication([]);install_wheel_guard();install_wheel_guard()
    root=QWidget();layout=QVBoxLayout(root);scroll=QScrollArea();scroll.setWidgetResizable(True);layout.addWidget(scroll)
    body=QWidget();fields=QVBoxLayout(body);scroll.setWidget(body)
    spin=QDoubleSpinBox();spin.setRange(0,100);spin.setValue(50);fields.addWidget(spin)
    integer=QSpinBox();integer.setValue(50);fields.addWidget(integer)
    combo=QComboBox();combo.addItems([str(i) for i in range(100)]);combo.setCurrentIndex(50);fields.addWidget(combo)
    slider=QSlider(Qt.Orientation.Horizontal);slider.setValue(50);fields.addWidget(slider)
    date=QDateTimeEdit();fields.addWidget(date)
    tabs=QTabBar();tabs.addTab('Automatic');tabs.addTab('Semi-Auto');fields.addWidget(tabs)
    fields.addStretch();body.setMinimumHeight(1800);root.resize(420,420);root.show();app.processEvents()
    def wheel(target,delta=-120):
        pos=target.rect().center()
        event=QWheelEvent(QPointF(pos),QPointF(target.mapToGlobal(pos)),QPoint(),QPoint(0,delta),
                          Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier,Qt.ScrollPhase.ScrollUpdate,False)
        QApplication.sendEvent(target,event)
    initial=(spin.value(),integer.value(),combo.currentIndex(),slider.value(),date.dateTime(),tabs.currentIndex())
    for focused in (True,False):
        for target in (spin,spin.findChild(QLineEdit),integer,combo,slider,date,tabs):
            if focused:target.setFocus()
            else:target.clearFocus()
            wheel(target);wheel(target,120)
            assert initial==(spin.value(),integer.value(),combo.currentIndex(),slider.value(),date.dateTime(),tabs.currentIndex())
    scroll.verticalScrollBar().setValue(0);wheel(spin)
    assert scroll.verticalScrollBar().value()>0,'Wheel over an option must scroll surrounding panel'
    # Normal text entry and arrow controls remain usable.
    spin.lineEdit().selectAll();QTest.keyClicks(spin.lineEdit(),'61');QTest.keyClick(spin.lineEdit(),Qt.Key.Key_Return)
    assert spin.value()==61
    QTest.keyClick(spin,Qt.Key.Key_Up);assert spin.value()==62
    # App-level filter covers widgets created after startup, not only a scan.
    late=QSpinBox();late.setValue(15);wheel(late);assert late.value()==15
    # Open popup lists remain scrollable without committing a new option.
    combo.showPopup();app.processEvents();old=combo.currentIndex();wheel(combo.view().viewport())
    assert combo.currentIndex()==old;combo.hidePopup()
    root.close();late.close();app.processEvents()
    print('Wheel guard passed: focused/unfocused/nested/future controls, tabs, dropdown popup, panel scroll and keyboard editing.')


if __name__=='__main__':run()
