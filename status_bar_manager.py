from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel
from PySide6.QtWidgets import QLineEdit
from PySide6.QtWidgets import QStatusBar


class StatusBarManager:
    def __init__(self, main_window):
        self.main_window = main_window
        self.status_bar = main_window.statusBar()
        self._setup_widgets()
        self._setup_connections()

    def _setup_widgets(self):
        """Create and setup status bar widgets"""
        self.db_type = QLabel()
        self.user = QLabel()
        self.schema = QLabel()
        self.tables = QLabel()

        self.zoom_edit = QLineEdit()
        self.zoom_edit.setFixedWidth(70)
        self.zoom_edit.setAlignment(Qt.AlignCenter)
        self.zoom_edit.setText("100%")

        # Add all widgets to status bar
        self.status_bar.addWidget(self.db_type)
        self.status_bar.addWidget(QLabel("|"))
        self.status_bar.addWidget(self.user)
        self.status_bar.addWidget(QLabel("|"))
        self.status_bar.addWidget(self.schema)
        self.status_bar.addWidget(QLabel("|"))
        self.status_bar.addWidget(self.tables)
        self.status_bar.addWidget(QLabel("|"))
        self.status_bar.addWidget(QLabel("Zoom:"))
        self.status_bar.addWidget(self.zoom_edit)

    def _setup_connections(self):
        """Setup signal connections"""
        self.zoom_edit.returnPressed.connect(self._on_zoom_edit)

    def update_zoom(self, zoom_level: float):
        """Update zoom level display"""
        percentage = int(zoom_level * 100)
        self.zoom_edit.setText(f"{percentage}%")

    def _on_zoom_edit(self):
        """Handle manual zoom level entry"""
        try:
            text = self.zoom_edit.text().rstrip("%")
            percentage = float(text)
            if percentage <= 0:
                raise ValueError("Zoom must be positive")

            current_zoom = self.main_window.diagram_view.zoom_level * 100
            factor = percentage / current_zoom
            self.main_window.diagram_view.scale(factor, factor)
        except ValueError:
            self.update_zoom(self.main_window.diagram_view.zoom_level)

    def handle_zoom_edit(self):
        """Handle manual zoom level entry"""
        try:
            text = self.zoom_edit.text().rstrip("%")
            percentage = float(text)
            if percentage <= 0:
                raise ValueError("Zoom must be positive")

            current_zoom = self.main_window.diagram_view.zoom_level * 100
            factor = percentage / current_zoom
            self.main_window.diagram_view.scale(factor, factor)
        except ValueError:
            # Restore current zoom level if input was invalid
            self.update_zoom(self.main_window.diagram_view.zoom_level)

    def update_connection_info(
        self, db_type="", user="", schema="", total=0, selected=0
    ):
        """Update database connection information"""
        self.db_type.setText(f"DB: {db_type}")
        self.user.setText(f"User: {user}")
        self.schema.setText(f"Schema: {schema}")
        self.tables.setText(f"Tables: {selected}/{total}")
