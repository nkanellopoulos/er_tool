import atexit
import os
import os.path
import sys
import tempfile
from datetime import datetime
from typing import List
from urllib.parse import urlparse

from PySide6.QtCore import QProcess
from PySide6.QtCore import QRectF
from PySide6.QtCore import QSize
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtGui import QFont
from PySide6.QtGui import QIcon
from PySide6.QtGui import QPainter
from PySide6.QtSvgWidgets import QGraphicsSvgItem
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import QFileDialog
from PySide6.QtWidgets import QGraphicsScene
from PySide6.QtWidgets import QGraphicsView
from PySide6.QtWidgets import QHBoxLayout
from PySide6.QtWidgets import QLabel
from PySide6.QtWidgets import QLineEdit
from PySide6.QtWidgets import QMainWindow
from PySide6.QtWidgets import QMessageBox
from PySide6.QtWidgets import QSplitter
from PySide6.QtWidgets import QTreeWidget
from PySide6.QtWidgets import QTreeWidgetItem
from PySide6.QtWidgets import QTreeWidgetItemIterator
from PySide6.QtWidgets import QVBoxLayout
from PySide6.QtWidgets import QWidget

from connection_dialog import ConnectionDialog
from dot_generator import DotGenerator
from schema_reader import SchemaReader


class ERDiagramView(QGraphicsView):
    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene())
        self.setRenderHint(QPainter.Antialiasing)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        # self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.zoom_level = 1.0  # Track zoom level

    def wheelEvent(self, event):
        """Handle mouse wheel for panning and zooming"""
        if event.modifiers() & Qt.ControlModifier:
            # Zoom when Ctrl is pressed
            factor = 1.1
            if event.angleDelta().y() < 0:
                factor = 1.0 / factor
            self.scale(factor, factor)
        else:
            # Pan vertically and horizontally
            if event.modifiers() & Qt.ShiftModifier:
                # Horizontal scroll when Shift is pressed
                delta = event.angleDelta().y()
                self.horizontalScrollBar().setValue(
                    self.horizontalScrollBar().value() - delta
                )
            else:
                # Vertical scroll by default
                delta = event.angleDelta().y()
                self.verticalScrollBar().setValue(
                    self.verticalScrollBar().value() - delta
                )

    def scale(self, sx: float, sy: float):
        """Override scale to track zoom level"""
        super().scale(sx, sy)
        self.zoom_level *= sx
        # Notify parent about zoom change
        if hasattr(self, "on_zoom_changed"):
            self.on_zoom_changed(self.zoom_level)

    def resetTransform(self):
        """Override resetTransform to reset zoom level"""
        super().resetTransform()
        self.zoom_level = 1.0
        if hasattr(self, "on_zoom_changed"):
            self.on_zoom_changed(self.zoom_level)

    def fitInView(
        self, rect: QRectF, aspect_ratio_mode: Qt.AspectRatioMode = Qt.IgnoreAspectRatio
    ):
        """Override fitInView to track zoom level"""
        super().fitInView(rect, aspect_ratio_mode)
        # Calculate new zoom level based on the view scale
        transform = self.transform()
        self.zoom_level = transform.m11()  # Use horizontal scale factor
        if hasattr(self, "on_zoom_changed"):
            self.on_zoom_changed(self.zoom_level)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        # Store temporary files for cleanup on exit
        self.temp_files = []
        atexit.register(self.cleanup_temp_files)

        self.setWindowTitle("ER Diagram Tool")
        self.resize(1500, 800)

        # Create main widget and layout
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)

        # Add layout for connection settings
        settings_layout = QHBoxLayout()

        # Connection string input
        conn_layout = QHBoxLayout()
        conn_layout.addWidget(QLabel("Connection:"))
        self.conn_edit = QLineEdit()
        self.conn_edit.setText(os.getenv("DB_CONNECTION", ""))
        self.conn_edit.textChanged.connect(self.on_connection_changed)
        conn_layout.addWidget(self.conn_edit)
        settings_layout.addLayout(conn_layout)

        # Table prefix input
        prefix_layout = QHBoxLayout()
        prefix_layout.addWidget(QLabel("Table Prefix:"))
        self.prefix_edit = QLineEdit()
        self.prefix_edit.setText(os.getenv("TABLE_PREFIX", ""))
        self.prefix_edit.textChanged.connect(self.refresh_diagram)
        prefix_layout.addWidget(self.prefix_edit)
        settings_layout.addLayout(prefix_layout)

        layout.addLayout(settings_layout)

        # Create splitter for tree and diagram
        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter)

        # Create table tree
        self.table_tree = QTreeWidget()
        self.table_tree.setHeaderLabel("Tables")
        splitter.addWidget(self.table_tree)

        # Create diagram view
        self.diagram_view = ERDiagramView()
        splitter.addWidget(self.diagram_view)

        # Set splitter sizes
        splitter.setSizes([300, 900])

        # Set global toolbar style
        toolbar_style = """
            QToolBar {
                spacing: 10px;
                padding: 5px;
            }
            QToolBar QLabel {
                font-size: 14px;
                font-weight: bold;
                margin-left: 10px;
            }
            QToolBar QAction {
                font-size: 14px;
            }
        """
        self.setStyleSheet(toolbar_style)

        # Create toolbar with sections
        self.toolbar = self.addToolBar("Tools")
        self.toolbar.setIconSize(QSize(32, 32))  # Bigger icons
        self.toolbar.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)  # Text under icons

        # Create larger font for toolbar items
        toolbar_font = QFont()
        toolbar_font.setPointSize(14)  # Bigger font size

        # Create actions first
        zoom_in_action = QAction("Zoom In", self)
        zoom_in_action.setShortcut("Ctrl+=")  # Ctrl + = or else we have to press shift
        zoom_in_action.triggered.connect(lambda: self.diagram_view.scale(1.4, 1.4))

        zoom_out_action = QAction("Zoom Out", self)
        zoom_out_action.setShortcut("Ctrl+-")
        zoom_out_action.triggered.connect(lambda: self.diagram_view.scale(0.8, 0.8))

        zoom_100_action = QAction("100%", self)
        zoom_100_action.setShortcut("Ctrl+1")
        zoom_100_action.triggered.connect(self._zoom_100)

        fit_action = QAction("Fit View", self)
        fit_action.setShortcut("Ctrl+0")
        fit_action.triggered.connect(self.fit_view)

        select_all_action = QAction("Select All", self)
        select_all_action.setShortcut("Ctrl+A")
        select_all_action.triggered.connect(self.select_all_tables)

        deselect_all_action = QAction("Deselect All", self)
        deselect_all_action.setShortcut("Ctrl+D")
        deselect_all_action.triggered.connect(self.deselect_all_tables)

        refresh_action = QAction("Refresh", self)
        refresh_action.setShortcut("F5")
        refresh_action.triggered.connect(self.refresh_diagram)

        export_action = QAction("Export", self)
        export_action.setShortcut("Ctrl+S")
        export_action.triggered.connect(self.export_diagram)

        self.show_referenced_action = QAction("Show Referenced Tables", self)
        self.show_referenced_action.setCheckable(True)
        self.show_referenced_action.setChecked(False)
        self.show_referenced_action.triggered.connect(self.refresh_diagram)

        # Create menu bar
        menubar = self.menuBar()

        # View menu
        view_menu = menubar.addMenu("&View")
        view_menu.addAction(zoom_in_action)
        view_menu.addAction(zoom_out_action)
        view_menu.addAction(zoom_100_action)
        view_menu.addAction(fit_action)
        view_menu.addSeparator()
        view_menu.addAction(self.show_referenced_action)

        # Selection menu
        selection_menu = menubar.addMenu("&Selection")
        selection_menu.addAction(select_all_action)
        selection_menu.addAction(deselect_all_action)

        # Diagram menu
        diagram_menu = menubar.addMenu("&Diagram")
        diagram_menu.addAction(refresh_action)
        diagram_menu.addAction(export_action)

        # Help menu
        help_menu = menubar.addMenu("&Help")
        about_action = QAction("&About", self)
        about_action.triggered.connect(self.show_about_dialog)
        help_menu.addAction(about_action)

        # Helper function to load icons with proper color
        def load_icon(name: str) -> QIcon:
            icon_path = os.path.join(os.path.dirname(__file__), "icons", f"{name}.svg")
            if not os.path.exists(icon_path):
                print(f"Warning: Icon file not found: {icon_path}", file=sys.stderr)
                return QIcon()

            try:
                # Read SVG content
                with open(icon_path, "r", encoding="utf-8") as f:
                    svg_content = f.read()

                # Ensure XML declaration is present
                if not svg_content.startswith("<?xml"):
                    svg_content = (
                        '<?xml version="1.0" encoding="UTF-8"?>\n' + svg_content
                    )

                # Replace currentColor with actual color from palette
                # color = self.palette().text().color().name()
                svg_content = svg_content.replace("currentColor", "gray")

                # Create temporary file with modified SVG
                fd, tmp_path = tempfile.mkstemp(suffix=".svg")
                os.write(fd, svg_content.encode("utf-8"))
                os.close(fd)

                # Keep track of temporary file for cleanup
                self.temp_files.append(tmp_path)

                return QIcon(tmp_path)

            except Exception as e:
                print(f"Error loading icon {name}: {e}", file=sys.stderr)
                return QIcon()

        # Update changeEvent to handle theme changes
        def changeEvent(self, event):
            if event.type() == Qt.ApplicationPaletteChange:
                # Reload all toolbar icons
                for action in self.toolbar.actions():
                    if action.icon():
                        icon_name = action.data()  # Store icon name in action data
                        if icon_name:
                            action.setIcon(load_icon(icon_name))
            super().changeEvent(event)

        # Store icon names in action data for reloading
        for name, action in [
            ("zoom-in", zoom_in_action),
            ("zoom-out", zoom_out_action),
            ("zoom-100", zoom_100_action),
            ("zoom-fit-best", fit_action),
            ("dialog-ok-apply", select_all_action),
            ("edit-clear", deselect_all_action),
            ("view-refresh", refresh_action),
            ("document-save", export_action),
            ("dialog-ok", self.show_referenced_action),
        ]:
            action.setData(name)
            action.setIcon(load_icon(name))

        # View actions section
        section_label = QLabel("View: ")
        section_label.setFont(toolbar_font)
        self.toolbar.addWidget(section_label)

        self.toolbar.addAction(zoom_in_action)

        self.toolbar.addAction(zoom_out_action)

        self.toolbar.addAction(zoom_100_action)

        self.toolbar.addAction(fit_action)

        self.toolbar.addSeparator()

        # Selection actions
        section_label = QLabel("Selection: ")
        section_label.setFont(toolbar_font)
        self.toolbar.addWidget(section_label)

        self.toolbar.addAction(select_all_action)

        self.toolbar.addAction(deselect_all_action)

        self.toolbar.addSeparator()

        # Diagram actions
        section_label = QLabel("Diagram: ")
        section_label.setFont(toolbar_font)
        self.toolbar.addWidget(section_label)

        self.toolbar.addAction(refresh_action)

        self.toolbar.addAction(export_action)

        self.toolbar.addAction(self.show_referenced_action)

        self.db_name = "unknown"

        # Create status bar sections
        self.status_db_type = QLabel()
        self.status_user = QLabel()
        self.status_schema = QLabel()
        self.status_tables = QLabel()

        # Create zoom level editor
        self.zoom_edit = QLineEdit()
        self.zoom_edit.setFixedWidth(70)
        self.zoom_edit.setAlignment(Qt.AlignCenter)
        self.zoom_edit.setText("100%")
        self.zoom_edit.returnPressed.connect(self._on_zoom_edit)

        # Add sections to status bar
        status_bar = self.statusBar()
        status_bar.addWidget(self.status_db_type)
        status_bar.addWidget(QLabel("|"))
        status_bar.addWidget(self.status_user)
        status_bar.addWidget(QLabel("|"))
        status_bar.addWidget(self.status_schema)
        status_bar.addWidget(QLabel("|"))
        status_bar.addWidget(self.status_tables)
        status_bar.addWidget(QLabel("|"))
        status_bar.addWidget(QLabel("Zoom:"))
        status_bar.addWidget(self.zoom_edit)

        # Remove connection string from main window
        settings_layout.removeWidget(self.conn_edit)
        self.conn_edit.deleteLater()
        del self.conn_edit

        # Create connection action
        connect_action = QAction("Connect to Database", self)
        connect_action.setShortcut("Ctrl+B")  # B for database
        connect_action.triggered.connect(self.show_connection_dialog)

        # Add to menu and toolbar
        database_menu = menubar.addMenu("&Database")
        database_menu.addAction(connect_action)

        # Add database section to toolbar before the existing sections
        self.toolbar.insertWidget(None, QLabel("Database: "))
        self.toolbar.insertAction(None, connect_action)
        self.toolbar.insertSeparator(None)

        # Add database icon
        connect_action.setData("database")
        connect_action.setIcon(load_icon("database"))

        # Initialize connection from environment
        if os.getenv("DB_CONNECTION"):
            self.connection_string = os.getenv("DB_CONNECTION")
            self.load_tables()
        else:
            self.connection_string = ""
            self.update_status_bar()

        # Disconnect auto-refresh during bulk operations
        self.auto_refresh = True
        self.table_tree.itemChanged.connect(self.on_table_selection_changed)

        # Hook up zoom tracking
        self.diagram_view.on_zoom_changed = self._update_zoom_label

    def on_connection_changed(self):
        """Handle connection string changes"""
        if self.conn_edit.text():
            self.load_tables()

    def on_table_selection_changed(self, item, column):
        """Handle individual table selection changes"""
        if self.auto_refresh:
            self.refresh_diagram()
            self.update_status_bar()

    def select_all_tables(self):
        """Select all tables in the tree"""
        self.auto_refresh = False  # Disable auto-refresh
        iterator = QTreeWidgetItemIterator(self.table_tree)
        while iterator.value():
            iterator.value().setCheckState(0, Qt.Checked)
            iterator += 1
        self.auto_refresh = True  # Re-enable auto-refresh
        self.refresh_diagram()
        self.update_status_bar()

    def deselect_all_tables(self):
        """Deselect all tables in the tree"""
        self.auto_refresh = False  # Disable auto-refresh
        iterator = QTreeWidgetItemIterator(self.table_tree)
        while iterator.value():
            iterator.value().setCheckState(0, Qt.Unchecked)
            iterator += 1
        self.auto_refresh = True  # Re-enable auto-refresh
        self.refresh_diagram()
        self.update_status_bar()

    def fit_view(self):
        """Fit diagram to view"""
        if self.diagram_view.scene():
            self.diagram_view.fitInView(
                self.diagram_view.scene().itemsBoundingRect(), Qt.KeepAspectRatio
            )

    def _zoom_100(self):
        """Set zoom level to 100%"""
        self.diagram_view.resetTransform()
        self.diagram_view.scale(1.0, 1.0)
        self._update_zoom_label(1.0)

    def _update_zoom_label(self, zoom_level: float):
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

            # Calculate scale factor to reach desired zoom
            current_zoom = self.diagram_view.zoom_level * 100
            factor = percentage / current_zoom

            self.diagram_view.scale(factor, factor)
        except ValueError:
            # Restore current zoom level if input was invalid
            self._update_zoom_label(self.diagram_view.zoom_level)

    def load_tables(self):
        """Load tables from database and populate tree widget"""
        try:
            if not hasattr(self, "connection_string") or not self.connection_string:
                raise ValueError("No database connection string provided")

            # Extract database name from connection string
            parsed = urlparse(self.connection_string)
            self.db_name = parsed.path.strip("/")

            self.tables = SchemaReader.from_database(self.connection_string)

            # Populate tree widget
            self.table_tree.clear()
            for table_name in sorted(self.tables.keys()):
                item = QTreeWidgetItem(self.table_tree)
                item.setText(0, table_name)
                item.setCheckState(0, Qt.Unchecked)

            self.update_status_bar()

        except Exception as e:
            print(f"Error loading tables: {e}", file=sys.stderr)
            QMessageBox.warning(self, "Connection Error", str(e))

    def get_excluded_tables(self) -> List[str]:
        """Get list of unchecked tables"""
        excluded = []
        iterator = QTreeWidgetItemIterator(self.table_tree)
        while iterator.value():
            item = iterator.value()
            if item.checkState(0) == Qt.Unchecked:
                excluded.append(item.text(0))
            iterator += 1
        return excluded

    def refresh_diagram(self):
        """Generate and display the diagram"""
        try:
            generator = DotGenerator(
                self.tables, self.db_name, table_prefix=self.prefix_edit.text()
            )
            dot_content = generator.generate(
                exclude_tables=self.get_excluded_tables(),
                show_referenced=self.show_referenced_action.isChecked(),
            )

            # Create temporary files
            with tempfile.NamedTemporaryFile(suffix=".dot", delete=False) as dot_file:
                dot_file.write(dot_content.encode())
                dot_path = dot_file.name

            svg_path = dot_path + ".svg"

            # Run dot to generate SVG
            process = QProcess()
            process.start("dot", ["-Tsvg", dot_path, "-o", svg_path])
            process.waitForFinished()

            # Load SVG into view
            self.diagram_view.scene().clear()
            svg_item = QGraphicsSvgItem(svg_path)
            self.diagram_view.scene().addItem(svg_item)
            self.diagram_view.setSceneRect(QRectF(svg_item.boundingRect()))

            # Reset transform before fitting to view
            self.diagram_view.resetTransform()
            self.diagram_view.fitInView(svg_item, Qt.KeepAspectRatio)

            # Cleanup temporary files
            os.unlink(dot_path)
            os.unlink(svg_path)

            self.update_status_bar()  # Add status bar update at end of refresh

        except Exception as e:
            print(f"Error refreshing diagram: {e}", file=sys.stderr)

    def export_diagram(self):
        """Export current diagram to file"""
        try:
            # Generate default filename
            default_name = f"{self.db_name}_{datetime.now().strftime('%Y-%m-%d')}"
            file_name, _ = QFileDialog.getSaveFileName(
                self,
                "Export Diagram",
                default_name,
                "SVG files (*.svg);;PNG files (*.png);;PDF files (*.pdf)",
            )

            if file_name:
                # Generate DOT file
                generator = DotGenerator(self.tables, self.db_name)
                dot_content = generator.generate(
                    exclude_tables=self.get_excluded_tables()
                )

                # Create temporary dot file
                with tempfile.NamedTemporaryFile(
                    suffix=".dot", delete=False
                ) as dot_file:
                    dot_file.write(dot_content.encode())
                    dot_path = dot_file.name

                # Determine output format
                output_format = os.path.splitext(file_name)[1][1:]

                # Run dot to generate output file
                process = QProcess()
                process.start("dot", [f"-T{output_format}", dot_path, "-o", file_name])
                process.waitForFinished()

                # Cleanup
                os.unlink(dot_path)

        except Exception as e:
            print(f"Error exporting diagram: {e}", file=sys.stderr)

    def cleanup_temp_files(self):
        """Clean up temporary files on application exit"""
        for tmp_file in self.temp_files:
            try:
                if os.path.exists(tmp_file):
                    os.unlink(tmp_file)
            except Exception as e:
                print(
                    f"Error cleaning up temporary file {tmp_file}: {e}", file=sys.stderr
                )

    def show_about_dialog(self):
        """Show the About dialog"""
        QMessageBox.about(
            self,
            "About ER Diagram Tool",
            "ER Diagram Tool\n\n© Nikos Kanellopoulos, 2025",
        )

    def show_connection_dialog(self):
        """Show the database connection dialog"""
        dialog = ConnectionDialog(self)
        if hasattr(self, "connection_string"):
            dialog.set_connection_string(self.connection_string)

        # Connect to dialog's accepted signal
        dialog.accepted.connect(lambda: self._on_connection_accepted(dialog))

        # Show dialog non-modally
        dialog.show()

    def _on_connection_accepted(self, dialog: ConnectionDialog):
        """Handle accepted connection dialog"""
        self.connection_string = dialog.get_connection_string()
        self.load_tables()
        dialog.deleteLater()  # Clean up the dialog

    def update_status_bar(self):
        """Update status bar information"""
        if hasattr(self, "connection_string") and self.connection_string:
            try:
                db_type, rest = self.connection_string.split("://")
                auth, location = rest.split("@")
                user, _ = auth.split(":")  # Don't show password
                host_port, db = location.split("/")

                self.status_db_type.setText(f"DB: {db_type}")
                self.status_user.setText(f"User: {user}")
                self.status_schema.setText(f"Schema: {db}")

                if hasattr(self, "tables"):
                    total = len(self.tables)
                    selected = total - len(self.get_excluded_tables())
                    self.status_tables.setText(f"Tables: {selected}/{total}")
                else:
                    self.status_tables.setText("Tables: 0/0")
            except:
                self.status_db_type.setText("Not connected")
                self.status_user.setText("")
                self.status_schema.setText("")
                self.status_tables.setText("")
        else:
            self.status_db_type.setText("Not connected")
            self.status_user.setText("")
            self.status_schema.setText("")
            self.status_tables.setText("")


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
