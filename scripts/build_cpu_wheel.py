"""Rebuild llama-cpp-python 0.3.35 with the upstream forced Metal flag disabled."""
from pathlib import Path
import tarfile
import subprocess
import os

base = Path(__file__).resolve().parent.parent
archive = base / 'tmp' / 'llama_cpp_python-0.3.35.tar.gz'
source = base / 'tmp' / 'llama-cpu-source'
source.mkdir(exist_ok=True)
with tarfile.open(archive) as tar:
    tar.extractall(source, filter='data')
package = source / 'llama_cpp_python-0.3.35'
cmake = package / 'CMakeLists.txt'
cmake.write_text(cmake.read_text().replace('set(GGML_METAL "ON" CACHE BOOL "ggml: enable Metal" FORCE)',
                                         'set(GGML_METAL "OFF" CACHE BOOL "ggml: enable Metal" FORCE)'))
init = package / 'llama_cpp' / '__init__.py'
init.write_text(init.read_text().replace('0.3.35', '0.3.35+cpu'))
env = dict(os.environ)
env['PATH'] = str(base / '.venv' / 'bin') + os.pathsep + env['PATH']
env['CMAKE_ARGS'] = '-DGGML_METAL=OFF -DGGML_NATIVE=OFF -DGGML_ACCELERATE=ON -DCMAKE_OSX_DEPLOYMENT_TARGET=14.0'
env['MACOSX_DEPLOYMENT_TARGET'] = '14.0'
env['CMAKE_BUILD_PARALLEL_LEVEL'] = '4'
subprocess.run([str(base / '.venv/bin/python'), '-m', 'pip', 'wheel', '--no-index', '--no-deps', '--no-build-isolation',
                str(package), '--wheel-dir', str(base / 'wheels')], env=env, check=True)
