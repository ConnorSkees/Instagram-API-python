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

class UnsupportedMediaType(InstagramAPIException):
    """
    Media given was not in format supported by Instagramself

    Instagram currently supports:
        Images:
            .jpg
            .jpeg
            .gif
            .png
            .bmp

        Videos:
            .mp4
            .mov
    """

class SentryBlockException(InstagramAPIException):
    pass
