IPA Extractor (via SSH)
IPA Extractor is a PyQt6-based desktop application that allows you to extract .ipa files from apps installed on a jailbroken iPhone over an SSH connection. The application supports two main mechanisms: transferring and running an extraction script from your laptop, or running an existing script on your iPhone.

Features
SSH Connection: Connect to your iPhone via SSH using IP, username, and password.

Connection Indicator: Displays the SSH connection status (fast connected, slow connected, disconnected).

sshpass support: Allows password authentication directly from the GUI without external CLI interaction.

Two Extraction Mechanisms:
SCP Script: Transfers an extraction script (extract-ipa.sh) from your laptop to your iPhone and then runs it.

iPhone Script: Runs an existing extract-ipa.sh script on your iPhone.

App Bundle Path Detection: Automatically fetches a list of app bundle paths installed on your iPhone and provides them in a filterable dropdown.

Extract IPA: Runs a script to extract .ipa files from the selected app bundle path.
Download IPA: Downloads the extracted .ipa file from your iPhone to your laptop.
rsync support: Shows a progress bar for download operations if rsync is available on your system.
Log Output: Shows all outputs and errors from SSH/SCP/rsync commands in real-time.
Verbose Mode: Option to display the currently executing command in a log for debugging.
System Requirements
On Your Laptop/Computer (Where You Are Running This Application)
Python 3: Make sure Python 3 is installed.
PyQt6: Python GUI library.
OpenSSH Client: ssh, scp, rsync (optional for progress bar) must be installed and available in your system PATH.
sshpass (Optional but Recommended): For password authentication without external CLI prompt.
Ubuntu/Debian: sudo apt-get install sshpass
macOS (with Homebrew): brew install https://raw.githubusercontent.com/kadwanev/brew-sshpass/master/sshpass.rb
On your iPhone (Must be Jailbroken)
OpenSSH Server: Installed via Sileo, Zebra, Cydia, or another package manager.

rsync (Required): Important! rsync must be installed on your iPhone in order for the extraction script to work properly. You can install it via Sileo, Zebra, or another package manager. The app will display a warning if rsync is not found on your iPhone.

IPA Extraction Script: The extract-ipa.sh script that will be used to perform the extraction on your iPhone. This script should package the app into an .ipa file
