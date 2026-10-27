"""Fail-closed model integrity, source access and outbound connection guard."""
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import socket
import stat
from contextlib import contextmanager

class ModelUnavailable(RuntimeError):
    pass

def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def resolve_source(path, roots):
    path = Path(path).absolute()
    if path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise ValueError('Symbolic links are not accepted.')
    resolved = path.resolve()
    if not any(resolved.is_relative_to(Path(r).resolve()) for r in roots):
        raise ValueError('Path outside configured roots.')
    return resolved

@contextmanager
def open_readonly(path, roots):
    path = resolve_source(path, roots)
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            raise ValueError('Only regular files are accepted.')
        yield f


def verify_model(models, model_id):
    models = Path(models).resolve()
    try:
        manifest = json.loads((models / 'manifest.json').read_text())
        entry = manifest['models'][model_id]
        if not entry['files']:
            raise ValueError('Empty file inventory')
        for item in entry['files']:
            path = (models / item['path']).resolve()
            if not path.is_relative_to(models) or not path.is_file() or sha256(path) != item['sha256']:
                raise ValueError(f"Missing or altered model file: {item['path']}")
        target = (models / entry['path']).resolve()
        if not target.is_relative_to(models):
            raise ValueError('Invalid model location')
        actual = {str(p.relative_to(models)) for p in target.rglob('*') if p.is_file()} if target.is_dir() else {str(target.relative_to(models))}
        listed = {i['path'] for i in entry['files']}
        if not actual <= listed:
            raise ValueError('Unmanifested model files')
        return target, entry
    except (OSError, KeyError, ValueError) as exc:
        raise ModelUnavailable(f'{model_id} disabled: {exc}. Run the development bundler while connected.') from exc

_original_connect = socket.socket.connect
_original_connect_ex = socket.socket.connect_ex
_original_getaddrinfo = socket.getaddrinfo

def _local(address):
    if isinstance(address, str):
        return True  # Unix domain socket
    host = address[0]
    if host == 'localhost':
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False

def _connect(self, address):
    if os.environ.get('FILE_INTEL_DENY_ALL') == '1' or not _local(address):
        raise PermissionError('Offline mode blocks outbound network connections')
    return _original_connect(self, address)

def _connect_ex(self, address):
    if os.environ.get('FILE_INTEL_DENY_ALL') == '1' or not _local(address):
        raise PermissionError('Offline mode blocks outbound network connections')
    return _original_connect_ex(self, address)

def _getaddrinfo(host, *args, **kwargs):
    if host is not None and not _local((host, 0)):
        raise PermissionError('Offline mode blocks external DNS resolution')
    return _original_getaddrinfo(host, *args, **kwargs)

_enabled = False

def enable_offline():
    global _enabled
    if _enabled:
        return
    _enabled = True
    socket.socket.connect = _connect
    socket.socket.connect_ex = _connect_ex
    socket.getaddrinfo = _getaddrinfo
