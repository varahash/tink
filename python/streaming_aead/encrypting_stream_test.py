# Lint as: python3
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Tests for tink.python.streaming_aead.encrypting_stream."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import io
import sys

from absl.testing import absltest
# TODO(b/141106504) Replace this with unittest.mock
import mock

from tink.python.streaming_aead import encrypting_stream


def fake_get_output_stream_adapter(self, cc_primitive, aad, destination):
  del cc_primitive, aad, self  # unused
  return destination


class TestBytesObject(io.BytesIO):
  """A BytesIO object that does not close."""

  def close(self):
    pass


def get_encrypting_stream(ciphertext_destination, aad):
  return encrypting_stream.EncryptingStream(None, ciphertext_destination, aad)


class EncryptingStreamTest(absltest.TestCase):

  def setUp(self):
    super(EncryptingStreamTest, self).setUp()
    # Replace the EncryptingStream's staticmethod with a custom function to
    # avoid the need for a Streaming AEAD primitive.
    self.addCleanup(mock.patch.stopall)
    mock.patch.object(
        encrypting_stream.EncryptingStream,
        '_get_output_stream_adapter',
        new=fake_get_output_stream_adapter).start()

  def test_non_writable_object(self):
    f = mock.Mock()
    f.writable = mock.Mock(return_value=False)
    with self.assertRaisesRegex(ValueError, 'writable'):
      get_encrypting_stream(f, b'aad')

  def test_write(self):
    f = TestBytesObject()
    with get_encrypting_stream(f, b'aad') as es:
      es.write(b'Hello world!')

    self.assertEqual(b'Hello world!', f.getvalue())

  @absltest.skipIf(sys.version_info[0] == 2, 'Python 2 strings are bytes')
  def test_write_non_bytes(self):
    with io.BytesIO() as f, get_encrypting_stream(f, b'aad') as es:
      with self.assertRaisesRegex(TypeError, 'bytes-like object is required'):
        es.write('This is a string, not a bytes object')

  def test_textiowrapper_compatibility(self):
    """A test that checks the TextIOWrapper works as expected.

    It encrypts the same plaintext twice - once directly from bytes, and once
    through TextIOWrapper's encoding. The two ciphertexts should have the same
    length.
    """
    file_1 = TestBytesObject()
    file_2 = TestBytesObject()

    with get_encrypting_stream(file_1, b'aad') as es:
      with io.TextIOWrapper(es) as wrapper:
        # Need to specify this is a unicode string for Python 2.
        wrapper.write(u'some data')

    with get_encrypting_stream(file_2, b'aad') as es:
      es.write(b'some data')

    self.assertEqual(len(file_1.getvalue()), len(file_2.getvalue()))

  def test_flush(self):
    with io.BytesIO() as f, get_encrypting_stream(f, b'assoc') as es:
      es.write(b'Hello world!')
      es.flush()

  def test_closed(self):
    f = io.BytesIO()
    es = get_encrypting_stream(f, b'assoc')
    es.write(b'Hello world!')
    es.close()

    self.assertTrue(es.closed)
    self.assertTrue(f.closed)

  def test_closed_methods_raise(self):
    f = io.BytesIO()
    es = get_encrypting_stream(f, b'assoc')
    es.write(b'Hello world!')
    es.close()

    with self.assertRaisesRegex(ValueError, 'closed'):
      es.write(b'Goodbye world.')
    with self.assertRaisesRegex(ValueError, 'closed'):
      with es:
        pass
    with self.assertRaisesRegex(ValueError, 'closed'):
      es.flush()

  def test_unsupported_operation(self):
    with io.BytesIO() as f, get_encrypting_stream(f, b'assoc') as es:
      with self.assertRaisesRegex(io.UnsupportedOperation, 'seek'):
        es.seek(0, 2)
      with self.assertRaisesRegex(io.UnsupportedOperation, 'truncate'):
        es.truncate(0)
      with self.assertRaisesRegex(io.UnsupportedOperation, 'read'):
        es.read(-1)

  def test_inquiries(self):
    with io.BytesIO() as f, get_encrypting_stream(f, b'assoc') as es:
      self.assertTrue(es.writable())
      self.assertFalse(es.readable())
      self.assertFalse(es.seekable())

  def test_position(self):
    with io.BytesIO() as f:
      with get_encrypting_stream(f, b'assoc') as es:
        es.write(b'Hello world!')
        self.assertEqual(es.position(), 12)

  def test_position_works_closed(self):
    with io.BytesIO() as f:
      es = get_encrypting_stream(f, b'assoc')

      es.write(b'Hello world!')
      es.close()

      self.assertTrue(es.closed)
      self.assertEqual(es.position(), 12)

  def test_blocking_io(self):

    class OnlyWritesFirstFiveBytes(io.BytesIO):

      def write(self, buffer):
        buffer = buffer[:5]
        n = super(OnlyWritesFirstFiveBytes, self).write(buffer)
        return n

    with OnlyWritesFirstFiveBytes() as f:
      with get_encrypting_stream(f, b'assoc') as es:
        with self.assertRaisesRegex(io.BlockingIOError, 'could not complete'):
          es.write(b'Hello world!')

  def test_context_manager_exception_close(self):
    """Tests that exceptional exits do not trigger normal file closure.

    Instead, the file will be closed without a proper final ciphertext block,
    and will result in an invalid ciphertext. The ciphertext_destination file
    object itself should in most cases still be closed when garbage collected.
    """
    f = io.BytesIO()
    with self.assertRaisesRegex(ValueError, 'raised inside'):
      with get_encrypting_stream(f, b'assoc') as es:
        es.write(b'some message')
        raise ValueError('Error raised inside context manager')

    self.assertFalse(f.closed)


if __name__ == '__main__':
  absltest.main()
