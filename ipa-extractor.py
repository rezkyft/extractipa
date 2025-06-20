import sys
import subprocess
import os
import time # For measuring connection time
import re # Import regex module
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit, QLabel, QTextEdit,
    QFileDialog, QMessageBox, QGridLayout, QComboBox,
    QSpacerItem, QSizePolicy, QProgressBar, QCheckBox
)
from PyQt6.QtGui import QFont, QColor, QTextCharFormat, QTextCursor, QPainter, QBrush, QPen
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QSize

# QThread class to run SSH commands in the background
# This prevents the GUI from freezing while commands are executed
class WorkerThread(QThread):
    finished = pyqtSignal(str, str, int, float)  # stdout, stderr, returncode, time_taken
    error = pyqtSignal(str) # For general errors (e.g., command not found)
    progress_update = pyqtSignal(int) # New signal for progress updates
    log_message = pyqtSignal(str, str) # New signal to send logs to the main thread

    def __init__(self, command, measure_time=False, is_download=False):
        super().__init__()
        self.command = command
        self.measure_time = measure_time
        self.is_download = is_download # Flag to identify download operations

    def run(self):
        start_time = time.time()
        try:
            # Send the command to be executed to the main UI log
            self.log_message.emit(f"Executing command: {self.command}", "purple")

            # Use Popen to process output in real-time
            process = subprocess.Popen(
                self.command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True, # Get output as text
                encoding='utf-8', # Ensure output encoding
                bufsize=1 # Line-buffered output
            )

            stdout_lines = []
            stderr_lines = []

            while True:
                # Read stdout and stderr simultaneously
                stdout_line = process.stdout.readline()
                stderr_line = process.stderr.readline()

                if stdout_line:
                    stdout_lines.append(stdout_line)
                    if self.is_download:
                        # Try to parse progress from rsync output
                        # rsync --info=progress2 will output like '25% 1.23MB/s'
                        match = re.search(r'(\d+)%', stdout_line)
                        if match:
                            try:
                                progress_percent = int(match.group(1))
                                self.progress_update.emit(progress_percent)
                            except ValueError:
                                pass # Ignore if it cannot be converted to int

                if stderr_line:
                    stderr_lines.append(stderr_line)

                # Stop the loop if there's no more output and the process has ended
                if not stdout_line and not stderr_line and process.poll() is not None:
                    break

            # Wait for the process to finish and get the final returncode
            process.wait()
            end_time = time.time()
            time_taken = end_time - start_time

            self.finished.emit("".join(stdout_lines), "".join(stderr_lines), process.returncode, time_taken)

        except FileNotFoundError:
            self.error.emit("Error: SSH, SCP, or rsync command not found. Make sure it's installed and in your PATH.")
        except Exception as e:
            self.error.emit(f"An error occurred while running the command: {e}")

# Class for a blinking connection indicator
class ConnectionIndicator(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(QSize(10, 10)) # Dot size
        self._color = QColor("red") # Default: red (not connected)
        self.animation_timer = QTimer(self)
        self.animation_timer.timeout.connect(self._animate_dot)
        self.current_alpha = 255 # For blinking effect
        self.is_on = True # On/off status for blinking

        self.set_status("disconnected") # Set initial status

    def set_status(self, status, time_taken=None):
        if status == "connected_fast":
            self._color = QColor("#c0ffee")
            self.animation_timer.start(250) # Fast blink
            self.is_on = True
        elif status == "connected_slow":
            self._color = QColor("#fab52a")
            self.animation_timer.start(500) # Slower blink
            self.is_on = True
        elif status == "disconnected":
            self._color = QColor("#d6184f")
            self.animation_timer.stop() # Stop blinking
            self.is_on = True # Ensure it's fully visible (not blinking)
        self.update()

    def _animate_dot(self):
        # Change blinking to on/off
        self.is_on = not self.is_on
        self.current_alpha = 255 if self.is_on else 0 # Directly set alpha to 0 or 255
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        color_with_alpha = QColor(self._color)
        color_with_alpha.setAlpha(self.current_alpha) # Use the set alpha

        painter.setBrush(QBrush(color_with_alpha))
        painter.setPen(QPen(Qt.PenStyle.NoPen))
        painter.drawEllipse(0, 0, self.width(), self.height())


class IPAExtractorApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("IPA Extractor (via SSH)")
        self.setGeometry(100, 100, 1200, 600) # Increased window size for two panels

        self.ssh_connected = False
        self.ipa_available = False # Status of IPA availability for download
        self.last_generated_ipa_filename = None # To store the filename of the last generated IPA
        self.all_bundle_paths = [] # List to store all fetched bundle paths
        self.debug_mode = False # Default: debug mode off (cleaner log)

        self.init_ui()
        self._check_sshpass_availability()
        self._check_rsync_availability() # Check rsync availability
        self.connection_indicator.set_status("disconnected") # Set initial indicator status
        self._update_input_field_states() # Update input field states initially

        # Show rsync warning pop-up on iPhone
        self.show_rsync_warning_popup()

    def show_rsync_warning_popup(self):
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setText("Aplikasi ini membutuhkan modul rsync yang diinstal pada iPhone. Jika belum instal silakan instal terlebih dahulu melalui:\n\n1. Sileo\n2. Zebra\nAtau sejenisnya.")
        msg.setWindowTitle("Informasi Penting")
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()

    def init_ui(self):
        # Change main_layout to QGridLayout for more flexible positioning
        main_grid_layout = QGridLayout()
        self.setLayout(main_grid_layout) # Only one setLayout call here

        # Connection indicator in the top right corner
        self.connection_indicator = ConnectionIndicator(self)
        # Create a mini layout for the indicator to place it in the top right
        indicator_layout = QHBoxLayout()
        indicator_layout.addSpacerItem(QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed))
        indicator_layout.addWidget(self.connection_indicator)
        # Add the indicator to row 0, column 1 (right panel), top right alignment
        main_grid_layout.addLayout(indicator_layout, 0, 1, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)


        # --- Left Section: Configuration (25% width) ---
        left_panel_layout = QVBoxLayout()
        main_grid_layout.addLayout(left_panel_layout, 1, 0, 1, 1) # Row 1, Col 0, span 1x1

        # SSH Configuration Section
        ssh_config_group_layout = QGridLayout()
        left_panel_layout.addLayout(ssh_config_group_layout)

        # Labels and inputs for SSH Configuration
        row = 0
        ssh_config_group_layout.addWidget(QLabel("<h2>SSH Configuration</h2>"), row, 0, 1, 2, alignment=Qt.AlignmentFlag.AlignCenter)
        row += 1

        ssh_config_group_layout.addWidget(QLabel("IP Host:"), row, 0)
        self.ip_input = QLineEdit("192.168.1.XX") # Placeholder IP
        ssh_config_group_layout.addWidget(self.ip_input, row, 1)
        row += 1

        ssh_config_group_layout.addWidget(QLabel("Username:"), row, 0)
        self.username_input = QLineEdit("root") # Default username
        ssh_config_group_layout.addWidget(self.username_input, row, 1)
        row += 1

        ssh_config_group_layout.addWidget(QLabel("Password:"), row, 0)
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password) # Hide password
        ssh_config_group_layout.addWidget(self.password_input, row, 1)
        row += 1

        # Connect and Disconnect buttons in one QHBoxLayout
        connect_disconnect_layout = QHBoxLayout()
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self.test_ssh_connection)
        connect_disconnect_layout.addWidget(self.connect_btn)

        self.disconnect_btn = QPushButton("Disconnect")
        self.disconnect_btn.clicked.connect(self.disconnect_ssh)
        connect_disconnect_layout.addWidget(self.disconnect_btn)

        ssh_config_group_layout.addLayout(connect_disconnect_layout, row, 0, 1, 2) # Span 2 columns
        row += 1

        # Debug Mode Checkbox
        self.debug_checkbox = QCheckBox("Verbose")
        self.debug_checkbox.setChecked(self.debug_mode) # Set initial status
        self.debug_checkbox.toggled.connect(self._toggle_debug_mode)
        ssh_config_group_layout.addWidget(self.debug_checkbox, row, 0, 1, 2, alignment=Qt.AlignmentFlag.AlignLeft)
        row += 1


        # Script and Bundle Path Section
        path_group_layout = QGridLayout()
        left_panel_layout.addLayout(path_group_layout)

        path_group_layout.addWidget(QLabel("<h2>Environment Setting</h2>"), 0, 0, 1, 3, alignment=Qt.AlignmentFlag.AlignCenter)

        # Script Mechanism Dropdown
        path_group_layout.addWidget(QLabel("Technique :"), 1, 0)
        self.script_mechanism_combo = QComboBox()
        self.script_mechanism_combo.addItem("SCP Script")
        self.script_mechanism_combo.addItem("iPhone Script")
        self.script_mechanism_combo.currentIndexChanged.connect(self._update_script_mechanism_ui)
        path_group_layout.addWidget(self.script_mechanism_combo, 1, 1, 1, 2) # Span 2 columns for better layout

        # Group for Local Script widgets
        self.local_script_widgets = QWidget()
        local_script_h_layout = QHBoxLayout()
        local_script_h_layout.setContentsMargins(0, 0, 0, 0) # Remove extra margins
        self.local_script_widgets.setLayout(local_script_h_layout)

        self.local_script_path_input = QLineEdit()
        local_script_h_layout.addWidget(self.local_script_path_input)
        self.browse_local_script_btn = QPushButton("Choose File...")
        self.browse_local_script_btn.clicked.connect(self.browse_local_script_path)
        local_script_h_layout.addWidget(self.browse_local_script_btn)

        path_group_layout.addWidget(QLabel("Extractor Script (JS):"), 2, 0)
        path_group_layout.addWidget(self.local_script_widgets, 2, 1, 1, 2) # Add the widget holding the local script input and button

        # Script Path (on iPhone) - label and input on separate rows
        current_row = 3
        # Save reference to this label to change its text
        self.remote_script_label = QLabel("extract-ipa.sh Script (on iPhone):")
        path_group_layout.addWidget(self.remote_script_label, current_row, 0, 1, 3) # Label spans all 3 columns
        current_row += 1
        self.remote_script_path_input = QLineEdit()
        self.remote_script_path_input.setPlaceholderText("/var/mobile/Documents/extract-ipa.sh") # Default placeholder for transfer target
        path_group_layout.addWidget(self.remote_script_path_input, current_row, 0, 1, 3) # Input spans all 3 columns

        # Application Bundle Path (on iPhone) - label, filter input, dropdown, and refresh button
        current_row += 1
        path_group_layout.addWidget(QLabel("Application Bundle Path (on iPhone):"), current_row, 0, 1, 3) # Label spans all 3 columns
        current_row += 1

        # New filter input for bundle paths
        self.bundle_filter_input = QLineEdit()
        self.bundle_filter_input.setPlaceholderText("Filter bundles...")
        self.bundle_filter_input.textChanged.connect(self._filter_bundle_paths)
        path_group_layout.addWidget(self.bundle_filter_input, current_row, 0, 1, 3) # Filter input spans all 3 columns
        current_row += 1

        bundle_path_controls_layout = QHBoxLayout()
        self.bundle_path_combo = QComboBox() # Replaced QLineEdit with QComboBox
        self.bundle_path_combo.setEditable(False) # No longer editable for typing, only for selecting
        self.bundle_path_combo.setPlaceholderText("/var/containers/Bundle/Application/YOUR-UUID/YourApp.app")
        bundle_path_controls_layout.addWidget(self.bundle_path_combo)

        self.refresh_bundle_btn = QPushButton("Refresh")
        self.refresh_bundle_btn.clicked.connect(self.fetch_bundle_paths)
        bundle_path_controls_layout.addWidget(self.refresh_bundle_btn)

        path_group_layout.addLayout(bundle_path_controls_layout, current_row, 0, 1, 3) # Dropdown and button in column 0, span 3

        # Action Buttons Section (moved to left panel)
        action_button_layout = QHBoxLayout() # Changed back to QHBoxLayout as there are 2 potential buttons
        left_panel_layout.addLayout(action_button_layout)

        # Buttons for Local Script (Transfer & Run)
        self.transfer_script_btn = QPushButton("Start")
        self.transfer_script_btn.clicked.connect(self.transfer_and_run_script)
        action_button_layout.addWidget(self.transfer_script_btn)

        # Buttons for iPhone Script (Run Only) - Recreated
        self.run_script_btn = QPushButton("Start") #iphonescript
        self.run_script_btn.clicked.connect(self.run_script_on_iphone) # Connect to run_script_on_iphone function
        action_button_layout.addWidget(self.run_script_btn)

        # New Download IPA button
        self.download_ipa_btn = QPushButton("Download IPA")
        self.download_ipa_btn.clicked.connect(self.download_ipa_from_iphone)
        action_button_layout.addWidget(self.download_ipa_btn)


        # Add spacer so content doesn't stick to the top
        left_panel_layout.addStretch(1)


        # --- Right Section: Log Output Area (75% width) ---
        right_panel_layout = QVBoxLayout()
        main_grid_layout.addLayout(right_panel_layout, 1, 1, 1, 1) # Row 1, Col 1, span 1x1

        right_panel_layout.addWidget(QLabel("<h2></h2>"))
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setFont(QFont("Monospace", 10))
        right_panel_layout.addWidget(self.log_output)

        # QProgressBar for download progress
        self.download_progress_bar = QProgressBar(self)
        self.download_progress_bar.setAlignment(Qt.AlignmentFlag.AlignCenter) # Text in center
        self.download_progress_bar.setFormat("Downloading: %p%") # Text format
        self.download_progress_bar.setVisible(False) # Hidden by default
        right_panel_layout.addWidget(self.download_progress_bar)


        # Set column width ratio
        main_grid_layout.setColumnStretch(0, 25) # Left panel (25%)
        main_grid_layout.setColumnStretch(1, 75) # Right panel (75%)

        # Initial UI update based on default selection
        self._update_script_mechanism_ui(self.script_mechanism_combo.currentIndex())
        self._check_sshpass_availability()
        self._update_button_states() # Update button states initially
        self._update_input_field_states() # Update input field states initially

    def _update_button_states(self):
        # Set button status based on SSH connection status
        is_ssh_ready = self.ssh_connected
        self.connect_btn.setEnabled(not is_ssh_ready) # Connect active if not connected
        self.disconnect_btn.setEnabled(is_ssh_ready) # Disconnect active if connected

        current_mechanism_index = self.script_mechanism_combo.currentIndex()

        if current_mechanism_index == 0: # Local Script
            self.transfer_script_btn.setEnabled(is_ssh_ready)
            self.run_script_btn.setEnabled(False) # Run button disabled for Local Script
            self.download_ipa_btn.setEnabled(is_ssh_ready and self.ipa_available and self.last_generated_ipa_filename is not None and self.rsync_available) # Only active if IPA is available, filename known, and rsync available
        else: # iPhone Script
            self.transfer_script_btn.setEnabled(False) # Transfer button disabled for iPhone Script
            self.run_script_btn.setEnabled(is_ssh_ready)
            self.download_ipa_btn.setEnabled(is_ssh_ready and self.ipa_available and self.last_generated_ipa_filename is not None and self.rsync_available) # Only active if IPA is available, filename known, and rsync available

        self.refresh_bundle_btn.setEnabled(is_ssh_ready)
        self._update_input_field_states() # Call to update input field states

    def _update_input_field_states(self):
        # Set read-only status for IP, username, and password inputs
        is_connected = self.ssh_connected
        self.ip_input.setReadOnly(is_connected)
        self.username_input.setReadOnly(is_connected)
        self.password_input.setReadOnly(is_connected)
        # Make remote_script_path_input read-only when connected
        self.remote_script_path_input.setReadOnly(is_connected)
        # Bundle path filter input should always be active to filter the list, unless connection is being tested
        self.bundle_filter_input.setEnabled(True)


    def disconnect_ssh(self):
        self.ssh_connected = False
        self.ipa_available = False # Reset IPA status on disconnect
        self.last_generated_ipa_filename = None # Reset IPA filename
        self.connection_indicator.set_status("disconnected")
        self.display_log("SSH connection disconnected.", "#00face")
        self.download_progress_bar.setVisible(False) # Hide progress bar
        self.download_progress_bar.setValue(0) # Reset progress bar
        self._update_button_states() # Update button states
        self._update_input_field_states() # Update input field states

    def _check_sshpass_availability(self):
        try:
            subprocess.run("sshpass -V", shell=True, capture_output=True, check=True)
            self.sshpass_available = True
            self.display_log("sshpass found. Password authentication via GUI will be supported.", "#c0ffee")
        except (subprocess.CalledProcessError, FileNotFoundError):
            self.sshpass_available = False
            self.display_log("Warning: sshpass not found. Password authentication might require separate CLI interaction.", "orange")
            self.display_log("To install sshpass (Ubuntu/Debian): sudo apt-get install sshpass", "orange")
            self.display_log("To install sshpass (macOS with Homebrew): brew install https://raw.githubusercontent.com/kadwanev/brew-sshpass/master/sshpass.rb", "orange")

    def _check_rsync_availability(self):
        try:
            subprocess.run("rsync --version", shell=True, capture_output=True, check=True)
            self.rsync_available = True
            self.display_log("rsync found. Download progress will be displayed.", "#c0ffee")
        except (subprocess.CalledProcessError, FileNotFoundError):
            self.rsync_available = False
            self.display_log("Warning: rsync not found. IPA download will proceed without progress display (using scp fallback).", "orange")
            self.display_log("To install rsync (Ubuntu/Debian): sudo apt-get install rsync", "orange")
            self.display_log("To install rsync (macOS with Homebrew): brew install rsync", "orange")


    def _update_script_mechanism_ui(self, index):
        # Index 0 is "Local Script", Index 1 is "iPhone Script"
        if index == 0:  # Local Script selected
            self.local_script_widgets.setVisible(True)
            self.transfer_script_btn.setVisible(True) # Show transfer button
            self.run_script_btn.setVisible(False) # Hide run button
            # Change label text for "Path SCP Script (on iPhone)"
            self.remote_script_label.setText("Save Target Path:")
            # Change placeholder and default text when selecting "Local Script"
            self.remote_script_path_input.setPlaceholderText("/var/mobile/Documents/extract-ipa.sh")
            # If the user previously selected iPhone Script and remote_script_path_input is default,
            # then set default path for local script.
            # If the user has already input another path, leave it as is.
            if self.remote_script_path_input.text() == "/var/mobile/Documents/extract-ipa.sh" or \
               self.remote_script_path_input.text() == "/usr/local/bin/extract-ipa.sh" or \
               not self.remote_script_path_input.text(): # Also if empty
                self.remote_script_path_input.setText("/var/mobile/Documents/extract-ipa.sh")

        else:  # iPhone Script selected
            self.local_script_widgets.setVisible(False)
            self.transfer_script_btn.setVisible(False) # Hide transfer button
            self.run_script_btn.setVisible(True) # Show run button
            # Revert label text to "extract-ipa.sh Script (on iPhone)"
            self.remote_script_label.setText("extract-ipa.sh Script (on iPhone):")
            self.remote_script_path_input.setPlaceholderText("/var/mobile/Documents/extract-ipa.sh") # New placeholder for existing script
            self.remote_script_path_input.setText("/var/mobile/Documents/extract-ipa.sh") # Set actual text to new default
            # Clear local script path if changing from local to iPhone script, to avoid confusion
            self.local_script_path_input.clear()
        self._update_button_states() # Update button states after mechanism change


    def browse_local_script_path(self):
        # Open dialog to select extract-ipa.sh script file
        file_name, _ = QFileDialog.getOpenFileName(self, "Select extract-ipa.sh Script", "", "Shell Scripts (*.sh);;All Files (*)")
        if file_name:
            self.local_script_path_input.setText(file_name)
            # Automatically fill remote_script_path_input with the filename from the local script
            script_name = os.path.basename(file_name)
            # Ensure the default directory remains /var/mobile/Documents/
            self.remote_script_path_input.setText(f"/var/mobile/Documents/{script_name}")


    def display_log(self, text, color="black"):
        # Display text in the log area with a specific color
        cursor = self.log_output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        format = QTextCharFormat()
        format.setForeground(QColor(color))
        cursor.insertText(text + "\n", format)
        self.log_output.setTextCursor(cursor)
        self.log_output.verticalScrollBar().setValue(self.log_output.verticalScrollBar().maximum()) # Scroll to bottom

    def _handle_worker_log_message(self, message, color):
        """
        Slot to receive log messages from WorkerThread.
        Displays messages only if debug_mode is active or if the message is not an execution command.
        """
        if self.debug_mode or not message.startswith("Executing command:"):
            self.display_log(message, color)

    def _toggle_debug_mode(self, checked):
        """Enable/disable debug mode."""
        self.debug_mode = checked
        if self.debug_mode:
            self.display_log("Debug mode enabled (showing all commands).", "dark#c0ffee")
        else:
            self.display_log("Debug mode disabled (log will be cleaner).", "dark#c0ffee")

    def _build_ssh_command(self, action, password, ip, username, remote_path=None, local_path=None, bundle_path=None, remote_ls_path=None, remote_ipa_full_path=None, local_save_path=None):
        base_command = ""
        if action == "test_connection":
            # Simple command to test SSH connection
            base_command = f"ssh -P 22 {username}@{ip} 'echo Connected'"
        elif action == "transfer":
            base_command = f"scp -P 22 {local_path} {username}@{ip}:{os.path.dirname(remote_path)}"
        elif action == "execute":
            # This command will:
            # 1. Change to the script directory on iPhone (cd {remote_script_directory})
            # 2. Grant execute permission to the script (chmod +x extract-ipa.sh)
            # 3. Run the script with bundle path as argument (./extract-ipa.sh "bundle_path")
            # All this is done in one SSH command
            script_dir = os.path.dirname(remote_path)
            script_name = os.path.basename(remote_path)
            base_command = (
                f"ssh -P 22 {username}@{ip} "
                f"'cd \"{script_dir}\" && chmod +x \"./{script_name}\" && \"./{script_name}\" \"{bundle_path}\"'"
            )
        elif action == "list_bundles":
            base_command = (
                f"ssh -P 22 {username}@{ip} "
                f"'ls {remote_ls_path}'"
            )
        elif action == "download_ipa":
            if self.rsync_available:
                # Use rsync for progress
                base_command = f"rsync -avz --info=progress2 -e 'ssh -p 22' {username}@{ip}:\"{remote_ipa_full_path}\" \"{local_save_path}\""
            else:
                # Fallback to scp if rsync is not available (without progress)
                base_command = f"scp -P 22 {username}@{ip}:\"{remote_ipa_full_path}\" \"{local_save_path}\""

        if self.sshpass_available and password:
            return f"sshpass -p '{password}' {base_command}"
        else:
            return base_command

    def test_ssh_connection(self):
        ip = self.ip_input.text().strip()
        username = self.username_input.text().strip()
        password = self.password_input.text()

        if not ip or not username:
            QMessageBox.warning(self, "Input Error", "Please fill in iPhone IP and Username first.")
            return

        test_command = self._build_ssh_command("test_connection", password, ip, username)

        self.display_log(f"Attempting SSH connection test to {ip}...", "#00face")
        self.connect_btn.setEnabled(False)
        self.disconnect_btn.setEnabled(False) # Disable disconnect button also when trying to connect
        self.transfer_script_btn.setEnabled(False)
        self.run_script_btn.setEnabled(False) # Also disable this when testing connection
        self.refresh_bundle_btn.setEnabled(False)
        self.download_ipa_btn.setEnabled(False) # Disable download button
        self.ipa_available = False # Reset IPA status
        self.last_generated_ipa_filename = None # Reset IPA filename
        self.connection_indicator.set_status("disconnected") # Set to red when trying to connect
        self.download_progress_bar.setVisible(False) # Hide progress bar
        self.download_progress_bar.setValue(0) # Reset progress bar
        self._update_input_field_states() # Ensure input fields are non-editable when trying to connect

        self.test_worker = WorkerThread(test_command, measure_time=True)
        self.test_worker.finished.connect(self.on_test_connection_finished)
        self.test_worker.error.connect(self.on_worker_error)
        self.test_worker.log_message.connect(self._handle_worker_log_message) # Connect log signal to new handler
        self.test_worker.start()

    def on_test_connection_finished(self, stdout, stderr, returncode, time_taken):
        self.display_log("Transmission Status", "#f7f5de")
        if stdout:
            self.display_log(stdout, "black")
        if stderr:
            self.display_log(stderr, "red")

        if returncode == 0 and "Connected" in stdout:
            self.display_log(f"SSH connection successful! (Time: {time_taken:.2f}s)", "#c0ffee")
            self.ssh_connected = True
            self.ipa_available = False # Reset IPA status on new connection
            self.last_generated_ipa_filename = None # Reset IPA filename
            if time_taken < 1.0: # Threshold for fast connection (can be adjusted)
                self.connection_indicator.set_status("connected_fast")
            else:
                self.connection_indicator.set_status("connected_slow")
        else:
            self.display_log(f"SSH connection failed with code {returncode}.", "red")
            self.display_log("Please check IP, username, password, and if OpenSSH is installed on your iPhone.", "red")
            if "Permission denied" in stderr:
                self.display_log("Access denied. Check username and password.", "red")
            elif "Connection refused" in stderr or "Host unreachable" in stderr:
                self.display_log("Connection refused or host unreachable. Check IP and network.", "red")
            elif not self.sshpass_available and self.password_input.text():
                self.display_log("Warning: sshpass not installed, password might be requested in external CLI.", "orange")
            self.ssh_connected = False
            self.ipa_available = False
            self.last_generated_ipa_filename = None
            self.connection_indicator.set_status("disconnected")

        self._update_button_states() # Update button states based on new SSH connection status


    def transfer_and_run_script(self):
        # Function to transfer script via SCP and then run it via SSH
        if not self.ssh_connected:
            QMessageBox.warning(self, "Connection Error", "Please connect to SSH first using the 'Connect SSH' button.")
            return
        if self.script_mechanism_combo.currentIndex() != 0:
            QMessageBox.warning(self, "Input Error", "This button is only for 'Local Script' mechanism.")
            return

        local_script = self.local_script_path_input.text()
        ip = self.ip_input.text().strip()
        username = self.username_input.text().strip()
        password = self.password_input.text()
        remote_script = self.remote_script_path_input.text().strip()
        bundle_path = self.bundle_path_combo.currentText().strip() # Get from dropdown

        # Input validation
        if not local_script or not os.path.exists(local_script):
            QMessageBox.warning(self, "Input Error", "Please select a valid extract-ipa.sh script on your laptop.")
            return
        if not ip or not username or not remote_script or not bundle_path:
            QMessageBox.warning(self, "Input Error", "Please fill in all SSH details (IP, Username, Script Path on iPhone, Bundle Path).")
            return

        # Disable buttons during operation
        self.transfer_script_btn.setEnabled(False)
        self.run_script_btn.setEnabled(False) # Ensure run button is also disabled
        self.connect_btn.setEnabled(False)
        self.disconnect_btn.setEnabled(False)
        self.refresh_bundle_btn.setEnabled(False)
        self.download_ipa_btn.setEnabled(False) # Disable download button
        self.ipa_available = False # Reset IPA status before new operation
        self.last_generated_ipa_filename = None # Reset IPA filename
        self.download_progress_bar.setVisible(False) # Hide progress bar
        self.download_progress_bar.setValue(0) # Reset progress bar

        # Step 1: Transfer Script (SCP)
        scp_command = self._build_ssh_command(
            "transfer", password, ip, username,
            remote_path=remote_script, local_path=local_script
        )

        self.display_log(f"Attempting to transfer script: {scp_command}", "#00face")

        self.transfer_worker = WorkerThread(scp_command)
        # After transfer is finished, call on_transfer_finished_and_then_run
        self.transfer_worker.finished.connect(
            lambda stdout, stderr, returncode, time_taken:
                self.on_transfer_finished_and_then_run(
                    stdout, stderr, returncode, time_taken,
                    ip, username, password, remote_script, bundle_path
                )
        )
        self.transfer_worker.error.connect(self.on_worker_error)
        self.transfer_worker.log_message.connect(self._handle_worker_log_message) # Connect log signal to new handler
        self.transfer_worker.start()

    def on_transfer_finished_and_then_run(self, stdout, stderr, returncode, time_taken, ip, username, password, remote_script, bundle_path):
        self.display_log("Script Result", "#f7f5de")
        if stdout:
            self.display_log(stdout, "black")
        if stderr:
            self.display_log(stderr, "red")

        if returncode == 0:
            self.display_log("Script transferred successfully!", "#c0ffee")

            # Step 2: Run Script (SSH) after successful transfer
            ssh_command = self._build_ssh_command(
                "execute", password, ip, username,
                remote_path=remote_script, bundle_path=bundle_path
            )

            self.display_log(f"Attempting to run script on iPhone: {ssh_command}", "#00face")

            self.execute_worker = WorkerThread(ssh_command)
            self.execute_worker.finished.connect(self.on_execute_finished)
            self.execute_worker.error.connect(self.on_worker_error)
            self.execute_worker.log_message.connect(self._handle_worker_log_message) # Connect log signal to new handler
            self.execute_worker.start() # Start worker for execution
        else:
            self.display_log(f"Script transfer failed with code {returncode}.", "red")
            self.display_log("Please ensure IP, username, password are correct, and OpenSSH is installed on iPhone.", "red")
            if "Permission denied" in stderr:
                self.display_log("Access denied. Check username and password.", "red")
            elif "No such file or directory" in stderr:
                self.display_log("Destination directory on iPhone not found. Check script path on iPhone.", "red")
            elif not self.sshpass_available and self.password_input.text():
                self.display_log("Warning: sshpass not installed, password might be requested in external CLI.", "orange")

            # Re-enable buttons if transfer failed
            self._update_button_states()


    def fetch_bundle_paths(self):
        # Function to get a list of bundle folders from iPhone
        if not self.ssh_connected:
            QMessageBox.warning(self, "Connection Error", "Please connect to SSH first using the 'Connect SSH' button.")
            return

        ip = self.ip_input.text().strip()
        username = self.username_input.text().strip()
        password = self.password_input.text()

        if not ip or not username:
            QMessageBox.warning(self, "Input Error", "Please fill in iPhone IP and Username first.")
            return

        # Path for `ls`
        ls_path = "/var/containers/Bundle/Application/"
        ls_command = self._build_ssh_command(
            "list_bundles", password, ip, username,
            remote_ls_path=ls_path
        )

        self.display_log(f"Attempting to retrieve bundle list from: {ls_path}", "#00face")

        self.bundle_list_worker = WorkerThread(ls_command)
        self.bundle_list_worker.finished.connect(self.on_bundle_paths_fetched)
        self.bundle_list_worker.error.connect(self.on_worker_error)
        self.bundle_list_worker.log_message.connect(self._handle_worker_log_message) # Connect log signal to new handler
        self.refresh_bundle_btn.setEnabled(False) # Disable button while process is running
        self.transfer_script_btn.setEnabled(False) # Also disable transfer button
        self.run_script_btn.setEnabled(False) # Also disable run button
        self.download_ipa_btn.setEnabled(False) # Disable download button
        self.ipa_available = False # Reset IPA status
        self.last_generated_ipa_filename = None # Reset IPA filename
        self.download_progress_bar.setVisible(False) # Hide progress bar
        self.download_progress_bar.setValue(0) # Reset progress bar
        self.bundle_list_worker.start()

    def on_bundle_paths_fetched(self, stdout, stderr, returncode, time_taken): # Added time_taken
        self.display_log("Bundle List Output", "#869ef8")
        if stdout:
            self.display_log(stdout, "#f7f5de")
        if stderr:
            self.display_log(stderr, "red")

        if returncode == 0:
            self.display_log("Bundle list retrieved successfully!", "#c0ffee")
            self.all_bundle_paths = [] # Clear master list
            self.bundle_path_combo.clear() # Clear dropdown

            base_path = "/var/containers/Bundle/Application/"
            for line in stdout.splitlines():
                if line.strip(): # Ensure line is not empty
                    full_path = f"{base_path}{line.strip()}/"
                    self.all_bundle_paths.append(full_path) # Add to master list
                    self.bundle_path_combo.addItem(full_path) # Add to dropdown

            self.bundle_path_combo.setEditable(False) # No longer editable, only for selection
        else:
            self.display_log(f"Failed to retrieve bundle list with code {returncode}.", "red")
            self.display_log("Please ensure IP, username, and password are correct, and OpenSSH is installed on iPhone.", "red")
            if "Permission denied" in stderr:
                self.display_log("Access denied. Check username and password.", "red")
            elif "No such file or directory" in stderr:
                self.display_log("Directory '/var/containers/Bundle/Application/' not found on iPhone.", "red")
            elif not self.sshpass_available and self.password_input.text():
                self.display_log("Warning: sshpass not installed, password might be requested in external CLI.", "orange")

        self._update_button_states() # Re-enable buttons after completion
        self.bundle_path_combo.hidePopup() # Hide popup after refresh, let filter input control it

    def _filter_bundle_paths(self, text):
        # Temporarily block signals to prevent recursion when clearing/adding items
        self.bundle_path_combo.blockSignals(True)

        self.bundle_path_combo.clear()
        if text:
            # Filter bundle paths based on input text (case-insensitive)
            filtered_paths = [
                path for path in self.all_bundle_paths
                if text.lower() in path.lower()
            ]
            self.bundle_path_combo.addItems(filtered_paths)
            if filtered_paths:
                self.bundle_path_combo.showPopup() # Show popup if there are results
            else:
                self.bundle_path_combo.hidePopup() # Hide if no results
        else:
            # If text is empty, show all items again
            self.bundle_path_combo.addItems(self.all_bundle_paths)
            self.bundle_path_combo.hidePopup() # Hide popup if text is empty

        # Re-enable signals
        self.bundle_path_combo.blockSignals(False)


    def run_script_on_iphone(self):
        # Function to run script on iPhone via SSH (for iPhone Script)
        if not self.ssh_connected:
            QMessageBox.warning(self, "Connection Error", "Please connect to SSH first using the 'Connect SSH' button.")
            return
        # Ensure this is only called for iPhone Script
        if self.script_mechanism_combo.currentIndex() != 1:
            QMessageBox.warning(self, "Input Error", "This button is only for 'iPhone Script' mechanism.")
            return

        ip = self.ip_input.text().strip()
        username = self.username_input.text().strip()
        password = self.password_input.text()
        remote_script = self.remote_script_path_input.text().strip()

        # Get text from QComboBox
        bundle_path = self.bundle_path_combo.currentText().strip()

        # Input validation
        if not ip or not username or not remote_script or not bundle_path:
            QMessageBox.warning(self, "Input Error", "Please fill in all SSH details and script/bundle path on iPhone.")
            return

        ssh_command = self._build_ssh_command(
            "execute", password, ip, username,
            remote_path=remote_script, bundle_path=bundle_path
        )

        self.display_log(f"Attempting to run script on iPhone: {ssh_command}", "#00face")

        # Disable buttons during operation
        self.transfer_script_btn.setEnabled(False)
        self.run_script_btn.setEnabled(False)
        self.connect_btn.setEnabled(False)
        self.disconnect_btn.setEnabled(False)
        self.refresh_bundle_btn.setEnabled(False)
        self.download_ipa_btn.setEnabled(False) # Disable download button
        self.ipa_available = False # Reset IPA status before new operation
        self.last_generated_ipa_filename = None # Reset IPA filename
        self.download_progress_bar.setVisible(False) # Hide progress bar
        self.download_progress_bar.setValue(0) # Reset progress bar

        self.execute_worker = WorkerThread(ssh_command)
        self.execute_worker.finished.connect(self.on_execute_finished)
        self.execute_worker.error.connect(self.on_worker_error)
        self.execute_worker.log_message.connect(self._handle_worker_log_message) # Connect log signal to new handler
        self.execute_worker.start()

    def on_execute_finished(self, stdout, stderr, returncode, time_taken): # Added time_taken
        self.display_log("--- Script Execution Output ---", "#f7f5de")
        if stdout:
            self.display_log(stdout, "black")
        if stderr:
            self.display_log(stderr, "red")

        if returncode == 0:
            self.display_log("Script executed successfully on iPhone!", "#c0ffee")
            self.display_log("The .ipa file should have been created in the same directory as the script on iPhone.", "#c0ffee")
            self.ipa_available = True # Set IPA status to True on success

            # Extract actual IPA filename from stdout
            match = re.search(r"IPA: (.+\.ipa)", stdout)
            if match:
                self.last_generated_ipa_filename = match.group(1).strip()
                self.display_log(f"Detected IPA filename: {self.last_generated_ipa_filename}", "#c0ffee")
            else:
                self.display_log("Warning: Could not automatically detect IPA filename from script output.", "orange")
                self.last_generated_ipa_filename = None # Fallback if not found
                self.ipa_available = False # Consider IPA not fully ready for download if name unknown
        else:
            self.display_log(f"Script execution failed with code {returncode}.", "red")
            self.display_log("Please check IP, username, password, and script/bundle path on iPhone.", "red")
            if "Permission denied" in stderr:
                self.display_log("Access denied. Check username/password or script file permissions on iPhone.", "red")
            elif "command not found" in stderr:
                self.display_log("SSH or scp command not found on your laptop, or script not found on iPhone.", "red")
            elif "Error: application bundle directory DOES NOT exists." in stdout or "Error: application .app directory DOES NOT exists." in stdout:
                self.display_log("Application bundle path on iPhone is incorrect or does not exist.", "red")
            elif not self.sshpass_available and self.password_input.text():
                self.display_log("Warning: sshpass not installed, password might be requested in external CLI.", "orange")
            self.ipa_available = False # Set IPA status to False on failure
            self.last_generated_ipa_filename = None # Reset IPA filename

        self._update_button_states() # Re-enable buttons after completion

    def download_ipa_from_iphone(self):
        if not self.ssh_connected:
            QMessageBox.warning(self, "Connection Error", "Please connect to SSH first.")
            return
        # Check IPA availability and last generated IPA filename
        if not self.ipa_available or self.last_generated_ipa_filename is None:
            QMessageBox.warning(self, "IPA Not Ready", "IPA file not yet generated or its filename could not be determined from the last operation.")
            return
        if not self.rsync_available:
            QMessageBox.warning(self, "rsync Not Found", "rsync is not installed on your system. Download will proceed without progress display (using scp). Please install rsync for progress functionality.")


        ip = self.ip_input.text().strip()
        username = self.username_input.text().strip()
        password = self.password_input.text()
        remote_script_path = self.remote_script_path_input.text().strip()

        # Use the last detected IPA filename
        ipa_filename = self.last_generated_ipa_filename

        # IPA is generated in the same directory as the script
        remote_ipa_directory = os.path.dirname(remote_script_path)
        remote_ipa_full_path = os.path.join(remote_ipa_directory, ipa_filename)

        # Dialog to save file on laptop
        default_filename = ipa_filename # Use the derived IPA filename as default
        local_save_path, _ = QFileDialog.getSaveFileName(self, "Save IPA File", default_filename, "IPA Files (*.ipa);;All Files (*)")

        if not local_save_path:
            self.display_log("IPA download cancelled by user.", "#f7f5de")
            return

        # SCP or rsync command to pull file from iPhone to laptop
        # Format: scp username@ip:remote_path local_path
        download_command = self._build_ssh_command(
            "download_ipa", password, ip, username,
            remote_ipa_full_path=remote_ipa_full_path, local_save_path=local_save_path
        )

        self.display_log(f"Attempting to download IPA: {download_command}", "#00face")

        # Disable buttons during download operation
        self.transfer_script_btn.setEnabled(False)
        self.run_script_btn.setEnabled(False)
        self.connect_btn.setEnabled(False)
        self.disconnect_btn.setEnabled(False)
        self.refresh_bundle_btn.setEnabled(False)
        self.download_ipa_btn.setEnabled(False)

        # Show progress bar
        self.download_progress_bar.setValue(0)
        self.download_progress_bar.setVisible(True)


        self.download_worker = WorkerThread(download_command, is_download=True) # Set is_download to True
        self.download_worker.finished.connect(self.on_ipa_download_finished)
        self.download_worker.error.connect(self.on_worker_error)
        self.download_worker.progress_update.connect(self.download_progress_bar.setValue) # Connect progress signal
        self.download_worker.log_message.connect(self._handle_worker_log_message) # Connect log signal to new handler
        self.download_worker.start()

    def on_ipa_download_finished(self, stdout, stderr, returncode, time_taken):
        self.display_log("--- IPA Download Output ---", "#f7f5de")
        if stdout:
            self.display_log(stdout, "black")
        if stderr:
            self.display_log(stderr, "red")

        if returncode == 0:
            self.display_log("IPA file downloaded successfully!", "#c0ffee")
            self.download_progress_bar.setValue(100) # Ensure 100% after completion
        else:
            self.display_log(f"IPA download failed with code {returncode}.", "red")
            self.display_log("Please check if the IPA file exists on iPhone and paths are correct.", "red")
            if "No such file or directory" in stderr:
                self.display_log("IPA file not found on iPhone at the specified path.", "red")
            elif "Permission denied" in stderr:
                self.display_log("Permission denied when accessing IPA on iPhone.", "red")

        self.download_progress_bar.setVisible(False) # Hide progress bar after completion
        self.download_progress_bar.setValue(0) # Reset progress bar
        self._update_button_states() # Re-enable buttons after completion


    def on_worker_error(self, message):
        self.display_log(message, "darkred")
        QMessageBox.critical(self, "Error", message)
        self._update_button_states() # Ensure buttons are re-enabled if an error occurs
        self.connect_btn.setEnabled(True) # Also enable connect button
        self.connection_indicator.set_status("disconnected") # Set status to red if general error
        self.download_progress_bar.setVisible(False) # Hide progress bar
        self.download_progress_bar.setValue(0) # Reset progress bar
        self._update_input_field_states() # Ensure input fields are editable again if error

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = IPAExtractorApp()
    window.show()
    sys.exit(app.exec())
