"""Compact native location navigation; never execute the selected file."""
from pathlib import Path
import os
import subprocess
import sys

import streamlit as st


def location_target(raw_path, config):
    # Archive members are virtual: reveal their enclosing archive in your file manager.
    target = Path(str(raw_path).split('::', 1)[0]).resolve()
    if not any(target.is_relative_to(Path(root).resolve()) for root in config.roots):
        raise ValueError('This location is outside your connected folders.')
    if not target.exists():
        raise ValueError('This item has moved. Scan your library to update its location.')
    return target


def reveal_location(raw_path, config):
    target = location_target(raw_path, config)
    folder = target if target.is_dir() else target.parent
    if sys.platform == 'win32':
        os.startfile(str(folder))  # Open folders only; never execute a selected document.
        return
    if sys.platform == 'darwin':
        command = ['open', str(target)] if target.is_dir() else ['open', '-R', str(target)]
    else:
        command = ['xdg-open', str(folder)]
    subprocess.run(command, check=True, timeout=10, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def location_button(raw_path, config, key, label='Open location'):
    with st.container(key='location_' + key):
        if st.button(label, icon=':material/folder_open:', key='reveal_' + key,
                     help='Open the folder in your file manager. For files and archive members, open the containing folder.'):
            try:
                reveal_location(raw_path, config)
                st.toast('Location opened in your file manager.', icon=':material/folder_open:')
            except ValueError as exc:
                st.warning(str(exc))
            except (OSError, subprocess.SubprocessError):
                st.error('Your file manager could not open this location. Check that the folder is available on this device.')
