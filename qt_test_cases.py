"""Keep independent Qt clock/settings fixtures in independent OS processes."""
import subprocess
import sys
from pathlib import Path


def isolated_cases(count, callback, executable):
    if '--qt-case' in sys.argv:
        index = int(sys.argv[sys.argv.index('--qt-case') + 1])
        if not 0 <= index < count:
            raise ValueError('Invalid Qt test case')
        return callback(index)
    for index in range(count):
        subprocess.run([sys.executable, '-X', 'faulthandler', str(Path(sys.argv[0]).resolve()),
                        str(executable), '--qt-case', str(index)], check=True)
