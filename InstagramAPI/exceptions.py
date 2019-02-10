"""
Instagram API exceptions
"""

class InstagramAPIException(Exception):
    """
    Base Instagram exception
    """

class NotLoggedIn(InstagramAPIException):
    """
    User is not currently logged in
    """

class SentryBlockException(InstagramAPIException):
    pass
