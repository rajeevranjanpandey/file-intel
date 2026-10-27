"""Create a fresh, computer-specific environment without touching source documents."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import venv

if __package__:
    from .run import python_path
else:
    from run import python_path

PROJECT = Path(__file__).resolve().parents[1]


def install(offline=False, environment='.venv-local', ui_only=False):
    if sys.version_info[:2] != (3, 12):
        raise ValueError('Use Python 3.12 to install this project.')
    target = (PROJECT / environment).resolve()
    if not target.is_relative_to(PROJECT) or target == PROJECT:
        raise ValueError('Choose an environment directory inside the project.')
    if target.exists():
        raise ValueError('That environment already exists. Choose a fresh name with --env; existing environments are preserved.')
    if offline:
        subprocess.run([sys.executable, str(PROJECT / 'scripts/verify_bundle.py')], check=True, cwd=PROJECT)
    venv.EnvBuilder(with_pip=True).create(target)
    executable = python_path(target)
    env = os.environ.copy()
    env['PYTHONPYCACHEPREFIX'] = str(Path(tempfile.gettempdir()) / 'file-intel-install-bytecode')
    command = [str(executable), '-m', 'pip', 'install']
    if offline:
        command += ['--no-index', '--find-links', str(PROJECT / 'wheels')]
    if ui_only:
        command += ['streamlit>=1.63,<2', 'numpy>=1.26,<3']
    else:
        command += ['-r', str(PROJECT / ('requirements.lock' if offline else 'requirements.txt'))]
    subprocess.run(command, check=True, cwd=PROJECT, env=env)
    subprocess.run([str(executable), '-m', 'pip', 'check'], check=True, env=env)
    if not ui_only:
        subprocess.run([str(executable), '-m', 'app.cli', 'models', 'verify'], check=True, cwd=PROJECT, env=env)
    print('Environment ready. Start with python scripts/run.py or your operating system launcher.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--offline', action='store_true', help='Use a verified wheel bundle built for this operating system and processor.')
    parser.add_argument('--env', default='.venv-local')
    parser.add_argument('--ui-only', action='store_true', help='Install only the dashboard; AI indexing requires the full installation.')
    args = parser.parse_args()
    try:
        install(args.offline, args.env, args.ui_only)
    except (ValueError, subprocess.CalledProcessError) as exc:
        raise SystemExit(str(exc)) from exc
