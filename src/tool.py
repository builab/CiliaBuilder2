from chimerax.core.tools import ToolInstance

try:
    from chimerax.ui import MainToolWindow
    from Qt.QtWidgets import QWidget, QVBoxLayout, QLabel
except Exception:
    MainToolWindow = None
    QWidget = None


class CiliaBuilder2Tool(ToolInstance):
    SESSION_ENDURING = True

    def __init__(self, session, tool_name):
        super().__init__(session, tool_name)

        if MainToolWindow is None:
            session.logger.warning("Qt UI not available, tool window not created")
            return

        self.tool_window = MainToolWindow(self)

        root = QWidget()
        layout = QVBoxLayout()
        root.setLayout(layout)
        layout.addWidget(QLabel("CiliaBuilder2 UI skeleton\nCommands are the current test path."))

        self.tool_window.ui_area.setLayout(QVBoxLayout())
        self.tool_window.ui_area.layout().addWidget(root)
        self.tool_window.manage(placement="side")
