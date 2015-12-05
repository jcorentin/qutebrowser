# vim: ft=python fileencoding=utf-8 sts=4 sw=4 et:
#!/usr/bin/env python3

# Copyright 2014-2015 Florian Bruhin (The Compiler) <mail@qutebrowser.org>
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

"""Tests for qutebrowser.browser.adblock."""

import os
import zipfile

import pytest

from qutebrowser.browser import adblock
from qutebrowser.config import configexc


def create_text_files(files_names, directory):
    """Returns a list of text files created
    with given names in given directory."""
    directory = str(directory)
    created_files = []
    for file_name in files_names:
        test_file = os.path.join(directory, file_name)
        with open(test_file, 'w', encoding='utf-8') as current_file:
            current_file.write('inside ' + file_name)
        created_files.append(test_file)
    return created_files


def create_zipfile(files_names, directory):
    """Returns a zipfile populated with created files and its name."""
    directory = str(directory)
    files = create_text_files(files_names, directory)
    # include created files in a ZipFile
    zipfile_name = os.path.join(directory, 'test.zip')
    with zipfile.ZipFile(zipfile_name, 'w') as new_zipfile:
        for file_name in files:
            new_zipfile.write(file_name, arcname=os.path.basename(file_name))
            # Removes path from file name
    return new_zipfile, zipfile_name


class TestGuessZipFilename:
    """Test function adblock.guess_zip_filename()."""

    def test_with_single_file(self, tmpdir):
        """Zip provided only contains a single file."""
        zf = create_zipfile(['test_a'], tmpdir)[0]
        assert adblock.guess_zip_filename(zf) == 'test_a'

    def test_with_multiple_files(self, tmpdir):
        """Zip provided contains multiple files including hosts."""
        names = ['test_a', 'test_b', 'hosts', 'test_c']
        zf = create_zipfile(names, tmpdir)[0]
        assert adblock.guess_zip_filename(zf) == 'hosts'

    def test_without_hosts_file(self, tmpdir):
        """Zip provided does not contain any hosts file."""
        names = ['test_a', 'test_b', 'test_d', 'test_c']
        zf = create_zipfile(names, tmpdir)[0]
        with pytest.raises(FileNotFoundError):
            adblock.guess_zip_filename(zf)


class TestGetFileObj:
    """Test Function adblock.get_fileobj()."""

    def test_with_zipfile(self, tmpdir):
        """File provided is a zipfile."""
        names = ['test_a', 'test_b', 'hosts', 'test_c']
        zf_name = create_zipfile(names, tmpdir)[1]
        zipobj = open(zf_name, 'rb')
        assert adblock.get_fileobj(zipobj).read() == "inside hosts"

    def test_with_text_file(self, tmpdir):
        """File provided is not a zipfile."""
        test_file = open(create_text_files(['testfile'], tmpdir)[0], 'rb')
        assert adblock.get_fileobj(test_file).read() == "inside testfile"


class TestIsWhitelistedHost:
    """Test function adblock.is_whitelisted_host."""

    def test_without_option(self, config_stub):
        """Option host-blocking-whitelist does not exist."""
        config_stub.data = {'content': {}}
        with pytest.raises(configexc.NoOptionError):
            adblock.is_whitelisted_host('qutebrowser.org')

    def test_with_match(self, config_stub):
        """Given host is in the whitelist."""
        config_stub.data = {'content':
                            {'host-blocking-whitelist': ['qutebrowser.org']}}
        assert adblock.is_whitelisted_host('qutebrowser.org')

    def test_without_match(self, config_stub):
        """Given host is not in the whitelist."""
        config_stub.data = {'content':
                            {'host-blocking-whitelist':['qutebrowser.org']}}
        assert not adblock.is_whitelisted_host('cutebrowser.org')


class TestHostBlocker:
    """Test for class HostBlocker."""
    pass