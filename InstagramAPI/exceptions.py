"""
Instagram API exceptions
"""

class InstagramAPIException(Exception):
    """
    Base Instagram exception
    """

class NoLoginException(InstagramAPIException):
    """
    User is not currently logged in
    """

class AlbumLengthError(InstagramAPIException):
    """
    Album was given fewer than 2 or more than 10 images
    """

class SentryBlockException(InstagramAPIException):
    pass
