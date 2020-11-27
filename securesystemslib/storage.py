"""
<Program Name>
  storage.py

<Author>
  Joshua Lock <jlock@vmware.com>

<Started>
  April 9, 2020

<Copyright>
  See LICENSE for licensing information.

<Purpose>
  Provides an interface for filesystem interactions, StorageBackendInterface.
"""

from __future__ import absolute_import
from __future__ import unicode_literals

import abc
import errno
import logging
import os
import shutil

import six

import securesystemslib.exceptions

logger = logging.getLogger(__name__)

if six.PY2:
  FileNotFoundError = OSError # pragma: no cover



class StorageBackendInterface():
  """
  <Purpose>
  Defines an interface for abstract storage operations which can be implemented
  for a variety of storage solutions, such as remote and local filesystems.
  """

  __metaclass__ = abc.ABCMeta


  @abc.abstractmethod
  def get(self, filepath):
    """
    <Purpose>
      A context manager for 'with' statements that is used for retrieving files
      from a storage backend and cleans up the files upon exit.

        with storage_backend.get('/path/to/file') as file_object:
          # operations
        # file is now closed

    <Arguments>
      filepath:
        The full path of the file to be retrieved.

    <Exceptions>
      securesystemslib.exceptions.StorageError, if the file does not exist or is
      no accessible.

    <Returns>
      A ContextManager object that emits a file-like object for the file at
      'filepath'.
    """
    raise NotImplementedError # pragma: no cover


  @abc.abstractmethod
  def put(self, fileobj, filepath, permissions=None):
    """
    <Purpose>
      Store a file-like object in the storage backend.
      The file-like object is read from the beginning, not its current
      offset (if any).

    <Arguments>
      fileobj:
        The file-like object to be stored.

      filepath:
        The full path to the location where 'fileobj' will be stored.

      mode:
        Bit mask with custom file permissions for the file-like object. When
        computing mode, the current OS umask value is first masked out. If None,
        the default OS permissions apply.
        On Windows systems only the file’s read-only flag can be set. All other
        bits are ignored.

    <Exceptions>
      securesystemslib.exceptions.StorageError, if the file can not be stored.

    <Returns>
      None
    """
    raise NotImplementedError # pragma: no cover


  @abc.abstractmethod
  def remove(self, filepath):
    """
    <Purpose>
      Remove the file at 'filepath' from the storage.

    <Arguments>
      filepath:
        The full path to the file.

    <Exceptions>
      securesystemslib.exceptions.StorageError, if the file can not be removed.

    <Returns>
      None
    """
    raise NotImplementedError # pragma: no cover


  @abc.abstractmethod
  def getsize(self, filepath):
    """
    <Purpose>
      Retrieve the size, in bytes, of the file at 'filepath'.

    <Arguments>
      filepath:
        The full path to the file.

    <Exceptions>
      securesystemslib.exceptions.StorageError, if the file does not exist or is
      not accessible.

    <Returns>
      The size in bytes of the file at 'filepath'.
    """
    raise NotImplementedError # pragma: no cover


  @abc.abstractmethod
  def create_folder(self, filepath):
    """
    <Purpose>
      Create a folder at filepath and ensure all intermediate components of the
      path exist.
      Passing an empty string for filepath does nothing and does not raise an
      exception.

    <Arguments>
      filepath:
        The full path of the folder to be created.

    <Exceptions>
      securesystemslib.exceptions.StorageError, if the folder can not be
      created.

    <Returns>
      None
    """
    raise NotImplementedError # pragma: no cover


  @abc.abstractmethod
  def list_folder(self, filepath):
    """
    <Purpose>
      List the contents of the folder at 'filepath'.

    <Arguments>
      filepath:
        The full path of the folder to be listed.

    <Exceptions>
      securesystemslib.exceptions.StorageError, if the file does not exist or is
      not accessible.

    <Returns>
      A list containing the names of the files in the folder. May be an empty
      list.
    """
    raise NotImplementedError # pragma: no cover





class FilesystemBackend(StorageBackendInterface):
  """
  <Purpose>
    A concrete implementation of StorageBackendInterface which interacts with
    local filesystems using Python standard library functions.
  """

  # As FilesystemBackend is effectively a stateless wrapper around various
  # standard library operations, we only ever need a single instance of it.
  # That single instance is safe to be (re-)used by all callers. Therefore
  # implement the singleton pattern to avoid uneccesarily creating multiple
  # objects.
  _instance = None

  def __new__(cls, *args, **kwargs):
    if cls._instance is None:
      cls._instance = object.__new__(cls, *args, **kwargs)
    return cls._instance



  class GetFile(object):
    # Implementing get() as a function with the @contextmanager decorator
    # doesn't allow us to cleanly capture exceptions thrown by the underlying
    # implementation and bubble up our generic
    # securesystemslib.exceptions.StorageError, therefore we implement get as
    # a class and also assign the class to the 'get' attribute of the parent
    # FilesystemBackend class.

    def __init__(self, filepath):
      self.filepath = filepath


    def __enter__(self):
      try:
        self.file_object = open(self.filepath, 'rb')
        return self.file_object
      except (FileNotFoundError, IOError):
        raise securesystemslib.exceptions.StorageError(
            "Can't open %s" % self.filepath)


    def __exit__(self, exc_type, exc_val, traceback):
      self.file_object.close()



  # Map our class ContextManager implementation to the function expected of the
  # securesystemslib.storage.StorageBackendInterface.get definition
  get = GetFile


  def put(self, fileobj, filepath, mode=None):
    # If we are passed an open file, seek to the beginning such that we are
    # copying the entire contents
    if not fileobj.closed:
      fileobj.seek(0)

    # When calculating file permissions, the current OS umask value is first
    # masked out. If custom permissions are set, we calculate a new umask
    # followed by a call to open() with default permissions (0o777).
    # This trick is done since open() does not support mode(permissions) as
    # input parameter, alternatively os.open() can be used.


    # If a file with the same name already exists, the new permissions
    # may not be applied.
    try:
      os.remove(filepath)
    except OSError:
      pass


    try:
      if mode is None:
        fd = os.open(filepath, os.O_WRONLY|os.O_CREAT)
      else:
        fd = os.open(filepath, os.O_WRONLY|os.O_CREAT, mode)

      with os.fdopen(fd, "wb") as destination_file:
        shutil.copyfileobj(fileobj, destination_file)
        # Force the destination file to be written to disk from Python's internal
        # and the operating system's buffers.  os.fsync() should follow flush().
        destination_file.flush()
        os.fsync(destination_file.fileno())
    except (OSError, IOError):
      raise securesystemslib.exceptions.StorageError(
          "Can't write file %s" % filepath)



  def remove(self, filepath):
    try:
      os.remove(filepath)
    except (FileNotFoundError, PermissionError, OSError):  # pragma: no cover
      raise securesystemslib.exceptions.StorageError(
          "Can't remove file %s" % filepath)


  def getsize(self, filepath):
    try:
      return os.path.getsize(filepath)
    except OSError:
      raise securesystemslib.exceptions.StorageError(
          "Can't access file %s" % filepath)


  def create_folder(self, filepath):
    try:
      os.makedirs(filepath)
    except OSError as e:
      # 'OSError' raised if the leaf directory already exists or cannot be
      # created. Check for case where 'filepath' has already been created and
      # silently ignore.
      if e.errno == errno.EEXIST:
        pass
      elif e.errno == errno.ENOENT and not filepath:
        raise securesystemslib.exceptions.StorageError(
            "Can't create a folder with an empty filepath!")
      else:
        raise securesystemslib.exceptions.StorageError(
            "Can't create folder at %s" % filepath)


  def list_folder(self, filepath):
    try:
      return os.listdir(filepath)
    except FileNotFoundError:
      raise securesystemslib.exceptions.StorageError(
          "Can't list folder at %s" % filepath)
