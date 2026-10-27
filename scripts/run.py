"""Start the local application or run a command in this computer's environment."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[1]


def runtime_directory(project=PROJECT):
    key = hashlib.sha256(str(project.resolve()).encode()).hexdigest()[:16]
    return Path.home() / '.file-intel' / 'runtime' / key


def python_path(environment, platform=None):
    return Path(environment) / ('Scripts/python.exe' if (platform or sys.platform) == 'win32' else 'bin/python')


def select_python(env, environment=None):
    candidates = []
    caches = [runtime_directory()]
    if sys.platform == 'darwin':
        caches.append(Path.home() / 'Library/Application Support/File Intel/runtime')
    for cached in caches:
        try:
            info = json.loads((cached / 'ready.json').read_text())
            if Path(info['project']).resolve() == PROJECT:
                candidates.append((python_path(cached / '.venv'), cached / 'models'))
        except (OSError, ValueError, KeyError):
            pass
    candidates.extend((python_path(PROJECT / name), None) for name in ('.venv-local', '.venv', '.venv-intel'))
    candidates.append((Path(sys.executable), None))
    if environment:
        candidates = [(python_path(PROJECT / environment), None)]
    for executable, models in candidates:
        if not executable.is_file():
            continue
        try:
            check = subprocess.run([str(executable), '-c', 'import streamlit, numpy'], env=env,
                                   capture_output=True, timeout=15)
            if check.returncode == 0:
                if models:
                    env['FILE_INTEL_MODELS'] = str(models)
                return executable
        except (OSError, subprocess.TimeoutExpired):
            continue
    raise RuntimeError('No compatible environment found. Install Python 3.12, then run python scripts/install.py on this computer.')


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    env = os.environ.copy()
    key = hashlib.sha256(str(PROJECT).encode()).hexdigest()[:16]
    env['PYTHONPYCACHEPREFIX'] = str(Path(tempfile.gettempdir()) / 'file-intel-bytecode' / key)
    env['STREAMLIT_BROWSER_GATHER_USAGE_STATS'] = 'false'
    environment = None
    if args[:1] == ['--env']:
        if len(args) < 2:
            raise RuntimeError('Provide an environment directory after --env.')
        environment = args[1]
        args = args[2:]
    executable = select_python(env, environment)
    if args and args[0] == '--check':
        print('Compatible environment ready. Open http://127.0.0.1:8501 after starting the app.')
        return 0
    if args and args[0] == '--python':
        command = [str(executable), *args[1:]]
    else:
        command = [str(executable), '-m', 'streamlit', 'run', 'ui/app.py',
                   '--server.address', '127.0.0.1', '--server.port', '8501',
                   '--browser.gatherUsageStats', 'false', *args]
    return subprocess.call(command, cwd=PROJECT, env=env)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
