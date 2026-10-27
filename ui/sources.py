"""Native folder selection and a compact, persistent connection manager."""
from pathlib import Path
import json
import subprocess
import sys

import streamlit as st

from app.sources import add_folders


def choose_folders():
    if sys.platform != 'darwin':
        # The picker runs on its own main thread, outside the UI server thread.
        script = """import json, tkinter as tk
from tkinter import filedialog
root = tk.Tk()
root.withdraw()
try:
    selected = filedialog.askdirectory(title='Connect a folder to File Intel', mustexist=True)
    print(json.dumps([selected] if selected else []))
finally:
    root.destroy()
"""
        result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True, timeout=120)
        if result.returncode:
            raise ValueError('The folder picker could not open. Use Enter folder paths below.')
        return [Path(p) for p in json.loads(result.stdout)]
    # Fixed script: paths returned by the OS are never interpolated into code.
    script = '''set selectedFolders to choose folder with prompt "Connect folders to File Intel" with multiple selections allowed
set output to ""
repeat with selectedFolder in selectedFolders
    set output to output & POSIX path of selectedFolder & ASCII character 0
end repeat
return output'''
    result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True, timeout=120)
    if result.returncode:
        if '(-128)' in result.stderr:  # User cancelled the picker.
            return []
        raise ValueError('The folder picker could not open. Use Enter folder paths below.')
    return [Path(p) for p in result.stdout.rstrip('\n').split('\0') if p]


def render_connections(config, key='sources'):
    with st.popover('Connect folders', icon=':material/create_new_folder:', use_container_width=True):
        st.write('Build one library from several folders.')
        st.caption('Files and subfolders in each connected folder are indexed. Originals stay where they are.')
        if st.button('Choose folders on this device', icon=':material/folder_open:', key=key + '_picker'):
            try:
                picked = choose_folders()
                if picked:
                    added = add_folders(picked)
                    st.session_state['sources_notice'] = f'{len(added)} folders connected. Scan & Index to read their files.'
                    st.rerun()
            except (ValueError, OSError, subprocess.SubprocessError) as exc:
                st.warning(str(exc))
        with st.form(key + '_paths'):
            paths = st.text_area('Enter folder paths', placeholder='~/Documents\n~/Downloads',
                                 help='One folder per line. ~ means your current home folder. Add folders again to connect several.')
            if st.form_submit_button('Connect these folders'):
                try:
                    values = [p.strip() for p in paths.splitlines() if p.strip()]
                    if not values:
                        raise ValueError('Enter at least one folder path.')
                    added = add_folders(values)
                    st.session_state['sources_notice'] = f'{len(added)} folders connected. Scan & Index to read their files.'
                    st.rerun()
                except (ValueError, OSError) as exc:
                    st.warning(str(exc))
