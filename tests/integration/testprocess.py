# vim: ft=python fileencoding=utf-8 sts=4 sw=4 et:

# Copyright 2015 Florian Bruhin (The Compiler) <mail@qutebrowser.org>
#
# This file is part of qutebrowser.
#
# qutebrowser is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# qutebrowser is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with qutebrowser.  If not, see <http://www.gnu.org/licenses/>.

"""Base class for a subprocess run for tests.."""

import re
import os
import time

import pytestqt.plugin
from PyQt5.QtCore import pyqtSlot, pyqtSignal, QProcess, QObject, QElapsedTimer
from PyQt5.QtTest import QSignalSpy

from helpers import utils


class InvalidLine(Exception):

    """Raised when the process prints a line which is not parsable."""

    pass


class ProcessExited(Exception):

    """Raised when the child process did exit."""

    pass


class WaitForTimeout(Exception):

    """Raised when wait_for didn't get the expected message."""


class BlacklistedMessageError(Exception):

    """Raised when ensure_not_logged found a message."""


class Line:

    """Container for a line of data the process emits.

    Attributes:
        data: The raw data passed to the constructor.
        waited_for: If Process.wait_for was used on this line already.
    """

    def __init__(self, data):
        self.data = data
        self.waited_for = False

    def __repr__(self):
        return '{}({!r})'.format(self.__class__.__name__, self.data)


class Process(QObject):

    """Abstraction over a running test subprocess process.

    Reads the log from its stdout and parses it.

    Attributes:
        _invalid: A list of lines which could not be parsed.
        _data: A list of parsed lines.
        proc: The QProcess for the underlying process.

    Signals:
        ready: Emitted when the server finished starting up.
        new_data: Emitted when a new line was parsed.
    """

    ready = pyqtSignal()
    new_data = pyqtSignal(object)
    KEYS = ['data']

    def __init__(self, parent=None):
        super().__init__(parent)
        self._invalid = []
        self._data = []
        self.proc = QProcess()
        self.proc.setReadChannel(QProcess.StandardError)

    def _parse_line(self, line):
        """Parse the given line from the log.

        Return:
            A self.ParseResult member.
        """
        raise NotImplementedError

    def _executable_args(self):
        """Get the executable and arguments to pass to it as a tuple."""
        raise NotImplementedError

    def _get_data(self):
        """Get the parsed data for this test.

        Also waits for 0.5s to make sure any new data is received.

        Subprocesses are expected to alias this to a public method with a
        better name.
        """
        self.proc.waitForReadyRead(500)
        self.read_log()
        return self._data

    def _wait_signal(self, signal, timeout=5000, raising=True):
        """Wait for a signal to be emitted.

        Should be used in a contextmanager.
        """
        blocker = pytestqt.plugin.SignalBlocker(
            timeout=timeout, raising=raising)
        blocker.connect(signal)
        return blocker

    @pyqtSlot()
    def read_log(self):
        """Read the log from the process' stdout."""
        if not hasattr(self, 'proc'):
            # I have no idea how this happens, but it does...
            return
        while self.proc.canReadLine():
            line = self.proc.readLine()
            line = bytes(line).decode('utf-8', errors='ignore').rstrip('\r\n')

            try:
                parsed = self._parse_line(line)
            except InvalidLine:
                self._invalid.append(line)
                print("INVALID: {}".format(line))
                continue

            if parsed is None:
                if self._invalid:
                    print("IGNORED: {}".format(line))
            else:
                self._data.append(parsed)
                self.new_data.emit(parsed)

    def start(self):
        """Start the process and wait until it started."""
        with self._wait_signal(self.ready, timeout=60000):
            self._start()

    def _start(self):
        """Actually start the process."""
        executable, args = self._executable_args()
        self.proc.readyRead.connect(self.read_log)
        self.proc.start(executable, args)
        ok = self.proc.waitForStarted()
        assert ok
        assert self.is_running()

    def before_test(self):
        """Restart process before a test if it exited before."""
        self._invalid = []
        if not self.is_running():
            self.start()

    def after_test(self):
        """Clean up data after each test.

        Also checks self._invalid so the test counts as failed if there were
        unexpected output lines earlier.
        """
        if self._invalid:
            # Wait for a bit so the full error has a chance to arrive
            time.sleep(1)
            # Exit the process to make sure we're in a defined state again
            self.terminate()
            self.clear_data()
            raise InvalidLine(self._invalid)

        self.clear_data()
        if not self.is_running():
            raise ProcessExited

    def clear_data(self):
        """Clear the collected data."""
        self._data.clear()

    def terminate(self):
        """Clean up and shut down the process."""
        self.proc.terminate()
        self.proc.waitForFinished()

    def is_running(self):
        """Check if the process is currently running."""
        return self.proc.state() == QProcess.Running

    def _match_data(self, value, expected):
        """Helper for wait_for to match a given value.

        The behavior of this method is slightly different depending on the
        types of the filtered values:

        - If expected is None, the filter always matches.
        - If the value is a string or bytes object and the expected value is
          too, the pattern is treated as a glob pattern (with only * active).
        - If the value is a string or bytes object and the expected value is a
          compiled regex, it is used for matching.
        - If the value is any other type, == is used.

        Return:
            A bool
        """
        regex_type = type(re.compile(''))
        if expected is None:
            return True
        elif isinstance(expected, regex_type):
            return expected.match(value)
        elif isinstance(value, (bytes, str)):
            return utils.pattern_match(pattern=expected, value=value)
        else:
            return value == expected

    def _wait_for_existing(self, override_waited_for, **kwargs):
        """Check if there are any line in the history for wait_for.

        Return: either the found line or None.
        """
        for line in self._data:
            matches = []

            for key, expected in kwargs.items():
                value = getattr(line, key)
                matches.append(self._match_data(value, expected))

            if all(matches) and (not line.waited_for or override_waited_for):
                # If we waited for this line, chances are we don't mean the
                # same thing the next time we use wait_for and it matches
                # this line again.
                line.waited_for = True
                return line
        return None

    def wait_for(self, timeout=None, *, override_waited_for=False, **kwargs):
        """Wait until a given value is found in the data.

        Keyword arguments to this function get interpreted as attributes of the
        searched data. Every given argument is treated as a pattern which
        the attribute has to match against.

        Args:
            timeout: How long to wait for the message.
            override_waited_for: If set, gets triggered by previous messages
                                 again.

        Return:
            The matched line.
        """
        __tracebackhide__ = True
        if timeout is None:
            if 'CI' in os.environ:
                timeout = 15000
            else:
                timeout = 5000
        if not kwargs:
            raise TypeError("No keyword arguments given!")
        for key in kwargs:
            assert key in self.KEYS

        # Search existing messages
        existing = self._wait_for_existing(override_waited_for, **kwargs)
        if existing is not None:
            return existing

        # If there is none, wait for the message
        spy = QSignalSpy(self.new_data)
        elapsed_timer = QElapsedTimer()
        elapsed_timer.start()

        while True:
            got_signal = spy.wait(timeout)
            if not got_signal or elapsed_timer.hasExpired(timeout):
                raise WaitForTimeout("Timed out after {}ms waiting for "
                                     "{!r}.".format(timeout, kwargs))

            for args in spy:
                assert len(args) == 1
                line = args[0]

                matches = []

                for key, expected in kwargs.items():
                    value = getattr(line, key)
                    matches.append(self._match_data(value, expected))

                if all(matches):
                    # If we waited for this line, chances are we don't mean the
                    # same thing the next time we use wait_for and it matches
                    # this line again.
                    line.waited_for = True
                    return line

    def ensure_not_logged(self, delay=500, **kwargs):
        """Make sure the data matching the given arguments is not logged.

        If nothing is found in the log, we wait for delay ms to make sure
        nothing arrives.
        """
        __tracebackhide__ = True
        try:
            line = self.wait_for(timeout=delay, override_waited_for=True,
                                 **kwargs)
        except WaitForTimeout:
            return
        else:
            raise BlacklistedMessageError(line)
