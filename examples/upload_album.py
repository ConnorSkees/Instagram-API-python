#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Use text editor to edit the script and type in valid Instagram username/password

from InstagramAPI import InstagramAPI

"""
## Uploading a timeline album (aka carousel aka sidecar).
"""
media = [
    {
        'type': 'photo',
        'file': '/path/to/your/photo.jpg',
        'usertags': [
            {
                'position': [0.5, 0.5],
                'user_id': '123456789',
            },
        ]
    },
    {
        'type': 'photo',
        'file': '/path/to/your/photo.jpg',
    },
    {
       'type'     : 'video',
       'file'     : '/path/to/your/video.mp4',
       'thumbnail': '/path/to/your/thumbnail.jpg'
    }
]
captionText = 'caption 3'  # Caption to use for the album.
ig = InstagramAPI("login", "password")
ig.login()
ig.uploadAlbum(media, caption=captionText)
