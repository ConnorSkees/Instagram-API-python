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

class SentryBlockException(InstagramAPIException):
    pass
