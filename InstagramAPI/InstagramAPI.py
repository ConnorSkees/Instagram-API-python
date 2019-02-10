#!/usr/bin/env python
# -*- coding: utf-8 -*-

import calendar
import copy
from datetime import datetime
import hashlib
import hmac
import json
import math
import os
import random
import sys
import time
import urllib
import urllib.parse
import uuid

import requests
from requests_toolbelt import MultipartEncoder
from requests.packages.urllib3.exceptions import InsecureRequestWarning

from .ImageUtils import getImageSize
from .exceptions import SentryBlockException

# Turn off InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

try:
    from moviepy.editor import VideoFileClip
except ImportError:
    print("Failed to import moviepy. Need only for Video upload.")

class InstagramAPI:
    API_URL = 'https://i.instagram.com/api/v1/'
    DEVICE_SETTINGS = {
        'manufacturer': 'Xiaomi',
        'model': 'HM 1SW',
        'android_version': 18,
        'android_release': '4.3'
    }
    USER_AGENT = 'Instagram 10.26.0 Android ({android_version}/{android_release}; 320dpi; 720x1280; {manufacturer}; {model}; armani; qcom; en_US)'.format(**DEVICE_SETTINGS)
    IG_SIG_KEY = '4f8732eb9ba7d1c8e8897a75d6474d4eb3f5279137431b2aafb71fafe2abe178'
    with open("./EXPERIMENTS.txt", mode='r') as experiments:
        EXPERIMENTS = experiments.read()
    SIG_KEY_VERSION = '4'

    # username            # Instagram username
    # password            # Instagram password
    # debug               # Debug
    # uuid                # UUID
    # device_id           # Device ID
    # username_id         # Username ID
    # token               # _csrftoken
    # isLoggedIn          # Session status
    # rank_token          # Rank token
    # IGDataPath          # Data storage path

    def __init__(
            self,
            username: str,
            password: str,
            debug: bool = False,
            IGDataPath=None
        ) -> None:
        m = hashlib.md5()
        m.update(username.encode('utf-8') + password.encode('utf-8'))
        self.device_id = self.generateDeviceId(m.hexdigest())
        self.setUser(username, password)
        self.isLoggedIn = False
        self.LastResponse = None
        self.s = requests.Session()

    def setUser(self, username: str, password: str):
        self.username = username
        self.password = password
        self.uuid = self.generateUUID(True)

    def setProxy(self, proxy=None):
        """
        Set proxy for all requests::

        Proxy format - user:password@ip:port
        """

        if proxy is not None:
            print('Set proxy!')
            proxies = {'http': proxy, 'https': proxy}
            self.s.proxies.update(proxies)

    def login(self, force: bool = False):
        if (not self.isLoggedIn or force):
            if (self.SendRequest('si/fetch_headers/?challenge_type=signup&guid=' + self.generateUUID(False), None, True)):

                data = {'phone_id': self.generateUUID(True),
                        '_csrftoken': self.LastResponse.cookies['csrftoken'],
                        'username': self.username,
                        'guid': self.uuid,
                        'device_id': self.device_id,
                        'password': self.password,
                        'login_attempt_count': '0'}

                if (self.SendRequest('accounts/login/', self.generateSignature(json.dumps(data)), True)):
                    self.isLoggedIn = True
                    self.username_id = self.LastJson["logged_in_user"]["pk"]
                    self.rank_token = "%s_%s" % (self.username_id, self.uuid)
                    self.token = self.LastResponse.cookies["csrftoken"]

                    self.syncFeatures()
                    self.autoCompleteUserList()
                    self.timelineFeed()
                    self.getv2Inbox()
                    self.getRecentActivity()
                    print("Login success!\n")
                    return True

    def syncFeatures(self):
        data = json.dumps({
            '_uuid': self.uuid,
            '_uid': self.username_id,
            'id': self.username_id,
            '_csrftoken': self.token,
            'experiments': self.EXPERIMENTS
        })
        return self.SendRequest('qe/sync/', self.generateSignature(data))

    def autoCompleteUserList(self):
        return self.SendRequest('friendships/autocomplete_user_list/')

    def timelineFeed(self):
        return self.SendRequest('feed/timeline/')

    def megaphoneLog(self):
        return self.SendRequest('megaphone/log/')

    def expose(self):
        data = json.dumps({
            '_uuid': self.uuid,
            '_uid': self.username_id,
            'id': self.username_id,
            '_csrftoken': self.token,
            'experiment': 'ig_android_profile_contextual_feed'
        })
        return self.SendRequest('qe/expose/', self.generateSignature(data))

    def logout(self):
        logout = self.SendRequest('accounts/logout/')

    def uploadPhoto(self, photo, caption=None, upload_id=None, is_sidecar=None):
        if upload_id is None:
            upload_id = str(int(time.time() * 1000))
        data = {
            'upload_id': upload_id,
            '_uuid': self.uuid,
            '_csrftoken': self.token,
            'image_compression': '{"lib_name":"jt","lib_version":"1.3.0","quality":"87"}',
            'photo': ('pending_media_%s.jpg' % upload_id, open(photo, 'rb'), 'application/octet-stream', {'Content-Transfer-Encoding': 'binary'})
        }
        if is_sidecar:
            data['is_sidecar'] = '1'
        m = MultipartEncoder(data, boundary=self.uuid)
        self.s.headers.update({'X-IG-Capabilities': '3Q4=',
                               'X-IG-Connection-Type': 'WIFI',
                               'Cookie2': '$Version=1',
                               'Accept-Language': 'en-US',
                               'Accept-Encoding': 'gzip, deflate',
                               'Content-type': m.content_type,
                               'Connection': 'close',
                               'User-Agent': self.USER_AGENT})
        response = self.s.post(self.API_URL + "upload/photo/", data=m.to_string())
        if response.status_code == 200:
            if self.configure(upload_id, photo, caption):
                self.expose()
        return False

    def uploadVideo(self, video, thumbnail, caption=None, upload_id=None, is_sidecar=None):
        if upload_id is None:
            upload_id = str(int(time.time() * 1000))
        data = {'upload_id': upload_id,
                '_csrftoken': self.token,
                'media_type': '2',
                '_uuid': self.uuid}
        if is_sidecar:
            data['is_sidecar'] = '1'
        m = MultipartEncoder(data, boundary=self.uuid)
        self.s.headers.update({'X-IG-Capabilities': '3Q4=',
                               'X-IG-Connection-Type': 'WIFI',
                               'Host': 'i.instagram.com',
                               'Cookie2': '$Version=1',
                               'Accept-Language': 'en-US',
                               'Accept-Encoding': 'gzip, deflate',
                               'Content-type': m.content_type,
                               'Connection': 'keep-alive',
                               'User-Agent': self.USER_AGENT})
        response = self.s.post(self.API_URL + "upload/video/", data=m.to_string())
        if response.status_code == 200:
            body = json.loads(response.text)
            upload_url = body['video_upload_urls'][3]['url']
            upload_job = body['video_upload_urls'][3]['job']

            videoData = open(video, 'rb').read()
            # solve issue #85 TypeError: slice indices must be integers or None or have an __index__ method
            request_size = int(math.floor(len(videoData) / 4))
            lastRequestExtra = (len(videoData) - (request_size * 3))

            headers = copy.deepcopy(self.s.headers)
            self.s.headers.update({
                'X-IG-Capabilities': '3Q4=',
                'X-IG-Connection-Type': 'WIFI',
                'Cookie2': '$Version=1',
                'Accept-Language': 'en-US',
                'Accept-Encoding': 'gzip, deflate',
                'Content-type': 'application/octet-stream',
                'Session-ID': upload_id,
                'Connection': 'keep-alive',
                'Content-Disposition': 'attachment; filename="video.mov"',
                'job': upload_job,
                'Host': 'upload.instagram.com',
                'User-Agent': self.USER_AGENT
            })
            for i in range(0, 4):
                start = i * request_size
                if i == 3:
                    end = i * request_size + lastRequestExtra
                else:
                    end = (i + 1) * request_size
                length = lastRequestExtra if i == 3 else request_size
                content_range = "bytes {start}-{end}/{lenVideo}".format(start=start, end=(end - 1),
                                                                        lenVideo=len(videoData)).encode('utf-8')

                self.s.headers.update({'Content-Length': str(end - start), 'Content-Range': content_range, })
                response = self.s.post(upload_url, data=videoData[start:start + length])
            self.s.headers = headers

            if response.status_code == 200:
                if self.configureVideo(upload_id, video, thumbnail, caption):
                    self.expose()
        return False

    def uploadAlbum(self, media, caption=None, upload_id=None):
        if not media:
            raise Exception("List of media to upload can't be empty.")

        if len(media) < 2 or len(media) > 10:
            raise Exception('Instagram requires that albums contain 2-10 items. You tried to submit {}.'.format(len(media)))

        # Figure out the media file details for ALL media in the album.
        # NOTE: We do this first, since it validates whether the media files are
        # valid and lets us avoid wasting time uploading totally invalid albums!
        for idx, item in enumerate(media):
            if not item.get('file', '') or item.get('tipe', ''):
                raise Exception('Media at index "{}" does not have the required "file" and "type" keys.'.format(idx))

            # $itemInternalMetadata = new InternalMetadata();
            # If usertags are provided, verify that the entries are valid.
            if item.get('usertags', []):
                self.throwIfInvalidUsertags(item['usertags'])

            # Pre-process media details and throw if not allowed on Instagram.
            if item.get('type', '') == 'photo':
                # Determine the photo details.
                # $itemInternalMetadata->setPhotoDetails(Constants::FEED_TIMELINE_ALBUM, $item['file']);
                pass

            elif item.get('type', '') == 'video':
                # Determine the video details.
                # $itemInternalMetadata->setVideoDetails(Constants::FEED_TIMELINE_ALBUM, $item['file']);
                pass

            else:
                raise Exception('Unsupported album media type "{}".'.format(item['type']))

            itemInternalMetadata = {}
            item['internalMetadata'] = itemInternalMetadata

        # Perform all media file uploads.
        for idx, item in enumerate(media):
            itemInternalMetadata = item['internalMetadata']
            item_upload_id = self.generateUploadId()
            if item.get('type', '') == 'photo':
                self.uploadPhoto(item['file'], caption=caption, is_sidecar=True, upload_id=item_upload_id)
                # $itemInternalMetadata->setPhotoUploadResponse($this->ig->internal->uploadPhotoData(Constants::FEED_TIMELINE_ALBUM, $itemInternalMetadata));

            elif item.get('type', '') == 'video':
                # Attempt to upload the video data.
                self.uploadVideo(item['file'], item['thumbnail'], caption=caption, is_sidecar=True, upload_id=item_upload_id)
                # $itemInternalMetadata = $this->ig->internal->uploadVideo(Constants::FEED_TIMELINE_ALBUM, $item['file'], $itemInternalMetadata);
                # Attempt to upload the thumbnail, associated with our video's ID.
                # $itemInternalMetadata->setPhotoUploadResponse($this->ig->internal->uploadPhotoData(Constants::FEED_TIMELINE_ALBUM, $itemInternalMetadata));
                pass
            item['internalMetadata']['upload_id'] = item_upload_id

        albumInternalMetadata = {}
        return self.configureTimelineAlbum(media, albumInternalMetadata, captionText=caption)

    def throwIfInvalidUsertags(self, usertags):
        for user_position in usertags:
            # Verify this usertag entry, ensuring that the entry is format
            # ['position'=>[0.0,1.0],'user_id'=>'123'] and nothing else.
            correct = True
            if isinstance(user_position, dict):
                position = user_position.get('position', None)
                user_id = user_position.get('user_id', None)

                if isinstance(position, list) and len(position) == 2:
                    try:
                        x = float(position[0])
                        y = float(position[1])
                        if x < 0.0 or x > 1.0:
                            correct = False
                        if y < 0.0 or y > 1.0:
                            correct = False
                    except:
                        correct = False
                try:
                    user_id = long(user_id)
                    if user_id < 0:
                        correct = False
                except:
                    correct = False
            if not correct:
                raise Exception('Invalid user entry in usertags array.')

    def configureTimelineAlbum(self, media, albumInternalMetadata, captionText='', location=None):
        endpoint = 'media/configure_sidecar/'
        albumUploadId = self.generateUploadId()

        date = datetime.utcnow().isoformat()
        childrenMetadata = []
        for item in media:
            itemInternalMetadata = item['internalMetadata']
            uploadId = itemInternalMetadata.get('upload_id', self.generateUploadId())
            if item.get('type', '') == 'photo':
                # Build this item's configuration.
                photoConfig = {'date_time_original': date,
                               'scene_type': 1,
                               'disable_comments': False,
                               'upload_id': uploadId,
                               'source_type': 0,
                               'scene_capture_type': 'standard',
                               'date_time_digitized': date,
                               'geotag_enabled': False,
                               'camera_position': 'back',
                               'edits': {'filter_strength': 1,
                                         'filter_name': 'IGNormalFilter'}
                               }
                # This usertag per-file EXTERNAL metadata is only supported for PHOTOS!
                if item.get('usertags', []):
                    # NOTE: These usertags were validated in Timeline::uploadAlbum.
                    photoConfig['usertags'] = json.dumps({'in': item['usertags']})

                childrenMetadata.append(photoConfig)
            if item.get('type', '') == 'video':
                # Get all of the INTERNAL per-VIDEO metadata.
                videoDetails = itemInternalMetadata.get('video_details', {})
                # Build this item's configuration.
                videoConfig = {'length': videoDetails.get('duration', 1.0),
                               'date_time_original': date,
                               'scene_type': 1,
                               'poster_frame_index': 0,
                               'trim_type': 0,
                               'disable_comments': False,
                               'upload_id': uploadId,
                               'source_type': 'library',
                               'geotag_enabled': False,
                               'edits': {
                                   'length': videoDetails.get('duration', 1.0),
                                   'cinema': 'unsupported',
                                   'original_length': videoDetails.get('duration', 1.0),
                                   'source_type': 'library',
                                   'start_time': 0,
                                   'camera_position': 'unknown',
                                   'trim_type': 0}
                               }

                childrenMetadata.append(videoConfig)
        # Build the request...
        data = {'_csrftoken': self.token,
                '_uid': self.username_id,
                '_uuid': self.uuid,
                'client_sidecar_id': albumUploadId,
                'caption': captionText,
                'children_metadata': childrenMetadata}
        self.SendRequest(endpoint, self.generateSignature(json.dumps(data)))
        response = self.LastResponse
        if response.status_code == 200:
            self.LastResponse = response
            self.LastJson = json.loads(response.text)
            return True
        else:
            print("Request return " + str(response.status_code) + " error!")
            # for debugging
            try:
                self.LastResponse = response
                self.LastJson = json.loads(response.text)
            except:
                pass
            return False

    def direct_message(self, text, recipients):
        if type(recipients) != type([]):
            recipients = [str(recipients)]
        recipient_users = '"",""'.join(str(r) for r in recipients)
        endpoint = 'direct_v2/threads/broadcast/text/'
        boundary = self.uuid
        bodies   = [
            {
                'type' : 'form-data',
                'name' : 'recipient_users',
                'data' : '[["{}"]]'.format(recipient_users),
            },
            {
                'type' : 'form-data',
                'name' : 'client_context',
                'data' : self.uuid,
            },
            {
                'type' : 'form-data',
                'name' : 'thread',
                'data' : '["0"]',
            },
            {
                'type' : 'form-data',
                'name' : 'text',
                'data' : text or '',
            },
        ]
        data = self.buildBody(bodies,boundary)
        self.s.headers.update (
            {
                'User-Agent' : self.USER_AGENT,
                'Proxy-Connection' : 'keep-alive',
                'Connection': 'keep-alive',
                'Accept': '*/*',
                'Content-Type': 'multipart/form-data; boundary={}'.format(boundary),
                'Accept-Language': 'en-en',
            }
        )
        #self.SendRequest(endpoint,post=data) #overwrites 'Content-type' header and boundary is missed
        response = self.s.post(self.API_URL + endpoint, data=data)

        if response.status_code == 200:
            self.LastResponse = response
            self.LastJson = json.loads(response.text)
            return True
        else:
            print ("Request return " + str(response.status_code) + " error!")
            # for debugging
            try:
                self.LastResponse = response
                self.LastJson = json.loads(response.text)
            except:
                pass
            return False

    def direct_share(self, media_id, recipients, text=None):
        if not isinstance(position, list):
            recipients = [str(recipients)]
        recipient_users = '"",""'.join(str(r) for r in recipients)
        endpoint = 'direct_v2/threads/broadcast/media_share/?media_type=photo'
        boundary = self.uuid
        bodies = [
            {
                'type': 'form-data',
                'name': 'media_id',
                'data': media_id,
            },
            {
                'type': 'form-data',
                'name': 'recipient_users',
                'data': '[["{}"]]'.format(recipient_users),
            },
            {
                'type': 'form-data',
                'name': 'client_context',
                'data': self.uuid,
            },
            {
                'type': 'form-data',
                'name': 'thread',
                'data': '["0"]',
            },
            {
                'type': 'form-data',
                'name': 'text',
                'data': text or '',
            },
        ]
        data = self.buildBody(bodies, boundary)
        self.s.headers.update({'User-Agent': self.USER_AGENT,
                               'Proxy-Connection': 'keep-alive',
                               'Connection': 'keep-alive',
                               'Accept': '*/*',
                               'Content-Type': 'multipart/form-data; boundary={}'.format(boundary),
                               'Accept-Language': 'en-en'})
        # self.SendRequest(endpoint,post=data) #overwrites 'Content-type' header and boundary is missed
        response = self.s.post(self.API_URL + endpoint, data=data)

        if response.status_code == 200:
            self.LastResponse = response
            self.LastJson = json.loads(response.text)
            return True
        else:
            print("Request return " + str(response.status_code) + " error!")
            # for debugging
            try:
                self.LastResponse = response
                self.LastJson = json.loads(response.text)
            except:
                pass
            return False

    def configureVideo(self, upload_id, video, thumbnail, caption=''):
        clip = VideoFileClip(video)
        self.uploadPhoto(photo=thumbnail, caption=caption, upload_id=upload_id)
        data = json.dumps({
            'upload_id': upload_id,
            'source_type': 3,
            'poster_frame_index': 0,
            'length': 0.00,
            'audio_muted': False,
            'filter_type': 0,
            'video_result': 'deprecated',
            'clips': {
                'length': clip.duration,
                'source_type': '3',
                'camera_position': 'back',
            },
            'extra': {
                'source_width': clip.size[0],
                'source_height': clip.size[1],
            },
            'device': self.DEVICE_SETTINGS,
            '_csrftoken': self.token,
            '_uuid': self.uuid,
            '_uid': self.username_id,
            'caption': caption,
        })
        return self.SendRequest('media/configure/?video=1', self.generateSignature(data))

    def configure(self, upload_id, photo, caption=''):
        (w, h) = getImageSize(photo)
        data = json.dumps({'_csrftoken': self.token,
                           'media_folder': 'Instagram',
                           'source_type': 4,
                           '_uid': self.username_id,
                           '_uuid': self.uuid,
                           'caption': caption,
                           'upload_id': upload_id,
                           'device': self.DEVICE_SETTINGS,
                           'edits': {
                               'crop_original_size': [w * 1.0, h * 1.0],
                               'crop_center': [0.0, 0.0],
                               'crop_zoom': 1.0
                           },
                           'extra': {
                               'source_width': w,
                               'source_height': h
                           }})
        return self.SendRequest('media/configure/?', self.generateSignature(data))

    def editMedia(self, mediaId, captionText=''):
        data = json.dumps({'_uuid': self.uuid,
                           '_uid': self.username_id,
                           '_csrftoken': self.token,
                           'caption_text': captionText})
        return self.SendRequest('media/' + str(mediaId) + '/edit_media/', self.generateSignature(data))

    def removeSelftag(self, mediaId):
        data = json.dumps({'_uuid': self.uuid,
                           '_uid': self.username_id,
                           '_csrftoken': self.token})
        return self.SendRequest('media/' + str(mediaId) + '/remove/', self.generateSignature(data))

    def mediaInfo(self, mediaId):
        data = json.dumps({'_uuid': self.uuid,
                           '_uid': self.username_id,
                           '_csrftoken': self.token,
                           'media_id': mediaId})
        return self.SendRequest('media/' + str(mediaId) + '/info/', self.generateSignature(data))

    def deleteMedia(self, mediaId, media_type=1):
        data = json.dumps({'_uuid': self.uuid,
                           '_uid': self.username_id,
                           '_csrftoken': self.token,
                           'media_type': media_type,
                           'media_id': mediaId})
        return self.SendRequest('media/' + str(mediaId) + '/delete/', self.generateSignature(data))

    def changePassword(self, newPassword):
        data = json.dumps({'_uuid': self.uuid,
                           '_uid': self.username_id,
                           '_csrftoken': self.token,
                           'old_password': self.password,
                           'new_password1': newPassword,
                           'new_password2': newPassword})
        return self.SendRequest('accounts/change_password/', self.generateSignature(data))

    def explore(self):
        return self.SendRequest('discover/explore/')

    def comment(self, mediaId, commentText):
        data = json.dumps({'_uuid': self.uuid,
                           '_uid': self.username_id,
                           '_csrftoken': self.token,
                           'comment_text': commentText})
        return self.SendRequest('media/' + str(mediaId) + '/comment/', self.generateSignature(data))

    def deleteComment(self, mediaId, commentId):
        data = json.dumps({'_uuid': self.uuid,
                           '_uid': self.username_id,
                           '_csrftoken': self.token})
        return self.SendRequest('media/' + str(mediaId) + '/comment/' + str(commentId) + '/delete/', self.generateSignature(data))

    def changeProfilePicture(self, photo):
        # TODO Instagram.php 705-775
        return False

    def removeProfilePicture(self):
        data = json.dumps({'_uuid': self.uuid,
                           '_uid': self.username_id,
                           '_csrftoken': self.token})
        return self.SendRequest('accounts/remove_profile_picture/', self.generateSignature(data))

    def setPrivateAccount(self):
        data = json.dumps({'_uuid': self.uuid,
                           '_uid': self.username_id,
                           '_csrftoken': self.token})
        return self.SendRequest('accounts/set_private/', self.generateSignature(data))

    def setPublicAccount(self):
        data = json.dumps({'_uuid': self.uuid,
                           '_uid': self.username_id,
                           '_csrftoken': self.token})
        return self.SendRequest('accounts/set_public/', self.generateSignature(data))

    def getProfileData(self):
        data = json.dumps({'_uuid': self.uuid,
                           '_uid': self.username_id,
                           '_csrftoken': self.token})
        return self.SendRequest('accounts/current_user/?edit=true', self.generateSignature(data))

    def editProfile(self, url, phone, first_name, biography, email, gender):
        data = json.dumps({'_uuid': self.uuid,
                           '_uid': self.username_id,
                           '_csrftoken': self.token,
                           'external_url': url,
                           'phone_number': phone,
                           'username': self.username,
                           'full_name': first_name,
                           'biography': biography,
                           'email': email,
                           'gender': gender})
        return self.SendRequest('accounts/edit_profile/', self.generateSignature(data))

    def getStory(self, usernameId):
        return self.SendRequest('feed/user/' + str(usernameId) + '/reel_media/')

    def getUsernameInfo(self, usernameId):
        return self.SendRequest('users/' + str(usernameId) + '/info/')

    def getSelfUsernameInfo(self):
        return self.getUsernameInfo(self.username_id)

    def getSelfSavedMedia(self):
        return self.SendRequest('feed/saved')

    def getRecentActivity(self):
        activity = self.SendRequest('news/inbox/?')
        return activity

    def getFollowingRecentActivity(self):
        activity = self.SendRequest('news/?')
        return activity

    def getv2Inbox(self):
        inbox = self.SendRequest('direct_v2/inbox/?')
        return inbox

    def getv2Threads(self, thread, cursor=None):
        endpoint = 'direct_v2/threads/{0}'.format(thread)
        if cursor is not None:
            endpoint += '?cursor={0}'.format(cursor)
        inbox = self.SendRequest(endpoint)
        return inbox

    def getUserTags(self, usernameId):
        tags = self.SendRequest('usertags/' + str(usernameId) + '/feed/?rank_token=' + str(self.rank_token) + '&ranked_content=true&')
        return tags

    def getSelfUserTags(self):
        return self.getUserTags(self.username_id)

    def tagFeed(self, tag):
        userFeed = self.SendRequest('feed/tag/' + str(tag) + '/?rank_token=' + str(self.rank_token) + '&ranked_content=true&')
        return userFeed

    def getMediaLikers(self, mediaId):
        likers = self.SendRequest('media/' + str(mediaId) + '/likers/?')
        return likers

    def getGeoMedia(self, usernameId):
        locations = self.SendRequest('maps/user/' + str(usernameId) + '/')
        return locations

    def getSelfGeoMedia(self):
        return self.getGeoMedia(self.username_id)

    def fbUserSearch(self, query):
        query = self.SendRequest('fbsearch/topsearch/?context=blended&query=' + str(query) + '&rank_token=' + str(self.rank_token))
        return query

    def searchUsers(self, query):
        query = self.SendRequest('users/search/?ig_sig_key_version=' + str(self.SIG_KEY_VERSION) + '&is_typeahead=true&query=' + str(query) + '&rank_token=' + str(self.rank_token))
        return query

    def searchUsername(self, usernameName):
        query = self.SendRequest('users/' + str(usernameName) + '/usernameinfo/')
        return query

    def syncFromAdressBook(self, contacts):
        return self.SendRequest('address_book/link/?include=extra_display_name,thumbnails', "contacts=" + json.dumps(contacts))

    def searchTags(self, query):
        query = self.SendRequest('tags/search/?is_typeahead=true&q=' + str(query) + '&rank_token=' + str(self.rank_token))
        return query

    def getTimeline(self):
        query = self.SendRequest('feed/timeline/?rank_token=' + str(self.rank_token) + '&ranked_content=true&')
        return query

    def getUserFeed(self, usernameId, maxid='', minTimestamp=None):
        query = self.SendRequest('feed/user/%s/?max_id=%s&min_timestamp=%s&rank_token=%s&ranked_content=true'
                                 % (usernameId, maxid, minTimestamp, self.rank_token))
        return query

    def getSelfUserFeed(self, maxid='', minTimestamp=None):
        return self.getUserFeed(self.username_id, maxid, minTimestamp)

    def getHashtagFeed(self, hashtagString, maxid=''):
        return self.SendRequest('feed/tag/' + hashtagString + '/?max_id=' + str(maxid) + '&rank_token=' + self.rank_token + '&ranked_content=true&')

    def searchLocation(self, query):
        locationFeed = self.SendRequest('fbsearch/places/?rank_token=' + str(self.rank_token) + '&query=' + str(query))
        return locationFeed

    def getLocationFeed(self, locationId, maxid=''):
        return self.SendRequest('feed/location/' + str(locationId) + '/?max_id=' + maxid + '&rank_token=' + self.rank_token + '&ranked_content=true&')

    def getPopularFeed(self):
        popularFeed = self.SendRequest('feed/popular/?people_teaser_supported=1&rank_token=' + str(self.rank_token) + '&ranked_content=true&')
        return popularFeed

    def getUserFollowings(self, usernameId, maxid=''):
        url = 'friendships/' + str(usernameId) + '/following/?'
        query_string = {'ig_sig_key_version': self.SIG_KEY_VERSION,
                        'rank_token': self.rank_token}
        if maxid:
            query_string['max_id'] = maxid
        if sys.version_info.major == 3:
            url += urllib.parse.urlencode(query_string)
        else:
            url += urllib.urlencode(query_string)
        return self.SendRequest(url)

    def getSelfUsersFollowing(self):
        return self.getUserFollowings(self.username_id)

    def getUserFollowers(self, usernameId, maxid=''):
        if maxid == '':
            return self.SendRequest('friendships/' + str(usernameId) + '/followers/?rank_token=' + self.rank_token)
        else:
            return self.SendRequest('friendships/' + str(usernameId) + '/followers/?rank_token=' + self.rank_token + '&max_id=' + str(maxid))

    def getSelfUserFollowers(self):
        return self.getUserFollowers(self.username_id)

    def getPendingFollowRequests(self):
        return self.SendRequest('friendships/pending?')

    def like(self, mediaId):
        data = json.dumps({'_uuid': self.uuid,
                           '_uid': self.username_id,
                           '_csrftoken': self.token,
                           'media_id': mediaId})
        return self.SendRequest('media/' + str(mediaId) + '/like/', self.generateSignature(data))

    def unlike(self, mediaId):
        data = json.dumps({'_uuid': self.uuid,
                           '_uid': self.username_id,
                           '_csrftoken': self.token,
                           'media_id': mediaId})
        return self.SendRequest('media/' + str(mediaId) + '/unlike/', self.generateSignature(data))

    def save(self, mediaId):
        data = json.dumps({'_uuid': self.uuid,
                           '_uid': self.username_id,
                           '_csrftoken': self.token,
                           'media_id': mediaId})
        return self.SendRequest('media/' + str(mediaId) + '/save/', self.generateSignature(data))

    def unsave(self, mediaId):
        data = json.dumps({'_uuid': self.uuid,
                           '_uid': self.username_id,
                           '_csrftoken': self.token,
                           'media_id': mediaId})
        return self.SendRequest('media/' + str(mediaId) + '/unsave/', self.generateSignature(data))

    def getMediaComments(self, mediaId, max_id=''):
        return self.SendRequest('media/' + mediaId + '/comments/?max_id=' + max_id)

    def setNameAndPhone(self, name='', phone=''):
        data = json.dumps({'_uuid': self.uuid,
                           '_uid': self.username_id,
                           'first_name': name,
                           'phone_number': phone,
                           '_csrftoken': self.token})
        return self.SendRequest('accounts/set_phone_and_name/', self.generateSignature(data))

    def getDirectShare(self):
        return self.SendRequest('direct_share/inbox/?')

    def backup(self):
        # TODO Instagram.php 1470-1485
        return False

    def approve(self, userId):
        data = json.dumps({
        '_uuid'         : self.uuid,
        '_uid'          : self.username_id,
        'user_id'       : userId,
        '_csrftoken'    : self.token
        })
        return self.SendRequest('friendships/approve/'+ str(userId) + '/', self.generateSignature(data))

    def ignore(self, userId):
        data = json.dumps({
        '_uuid'         : self.uuid,
        '_uid'          : self.username_id,
        'user_id'       : userId,
        '_csrftoken'    : self.token
        })
        return self.SendRequest('friendships/ignore/'+ str(userId) + '/', self.generateSignature(data))

    def follow(self, userId):
        data = json.dumps({'_uuid': self.uuid,
                           '_uid': self.username_id,
                           'user_id': userId,
                           '_csrftoken': self.token})
        return self.SendRequest('friendships/create/' + str(userId) + '/', self.generateSignature(data))

    def unfollow(self, userId):
        data = json.dumps({'_uuid': self.uuid,
                           '_uid': self.username_id,
                           'user_id': userId,
                           '_csrftoken': self.token})
        return self.SendRequest('friendships/destroy/' + str(userId) + '/', self.generateSignature(data))

    def block(self, userId):
        data = json.dumps({'_uuid': self.uuid,
                           '_uid': self.username_id,
                           'user_id': userId,
                           '_csrftoken': self.token})
        return self.SendRequest('friendships/block/' + str(userId) + '/', self.generateSignature(data))

    def unblock(self, userId):
        data = json.dumps({'_uuid': self.uuid,
                           '_uid': self.username_id,
                           'user_id': userId,
                           '_csrftoken': self.token})
        return self.SendRequest('friendships/unblock/' + str(userId) + '/', self.generateSignature(data))

    def userFriendship(self, userId):
        data = json.dumps({'_uuid': self.uuid,
                           '_uid': self.username_id,
                           'user_id': userId,
                           '_csrftoken': self.token})
        return self.SendRequest('friendships/show/' + str(userId) + '/', self.generateSignature(data))

    def getLikedMedia(self, maxid=''):
        return self.SendRequest('feed/liked/?max_id=' + str(maxid))

    def generateSignature(self, data, skip_quote=False):
        if not skip_quote:
            try:
                parsedData = urllib.parse.quote(data)
            except AttributeError:
                parsedData = urllib.quote(data)
        else:
            parsedData = data
        return 'ig_sig_key_version=' + self.SIG_KEY_VERSION + '&signed_body=' + hmac.new(self.IG_SIG_KEY.encode('utf-8'), data.encode('utf-8'), hashlib.sha256).hexdigest() + '.' + parsedData

    def generateDeviceId(self, seed):
        volatile_seed = "12345"
        m = hashlib.md5()
        m.update(seed.encode('utf-8') + volatile_seed.encode('utf-8'))
        return 'android-' + m.hexdigest()[:16]

    def generateUUID(self, type):
        generated_uuid = str(uuid.uuid4())
        if (type):
            return generated_uuid
        else:
            return generated_uuid.replace('-', '')

    def generateUploadId(self):
        return str(calendar.timegm(datetime.utcnow().utctimetuple()))

    def createBroadcast(self, previewWidth=1080, previewHeight=1920, broadcastMessage=''):
        data = json.dumps({'_uuid': self.uuid,
                           '_uid': self.username_id,
                           'preview_height': previewHeight,
                           'preview_width': previewWidth,
                           'broadcast_message': broadcastMessage,
                           'broadcast_type': 'RTMP',
                           'internal_only': 0,
                           '_csrftoken': self.token})
        return self.SendRequest('live/create/', self.generateSignature(data))

    def startBroadcast(self, broadcastId, sendNotification=False):
        data = json.dumps({'_uuid': self.uuid,
                           '_uid': self.username_id,
                           'should_send_notifications': int(sendNotification),
                           '_csrftoken': self.token})
        return self.SendRequest('live/' + str(broadcastId) + '/start', self.generateSignature(data))

    def stopBroadcast(self, broadcastId):
        data = json.dumps({'_uuid': self.uuid,
                           '_uid': self.username_id,
                           '_csrftoken': self.token})
        return self.SendRequest('live/' + str(broadcastId) + '/end_broadcast/', self.generateSignature(data))

    def addBroadcastToLive(self, broadcastId):
        # broadcast has to be ended first!
        data = json.dumps({'_uuid': self.uuid,
                           '_uid': self.username_id,
                           '_csrftoken': self.token})
        return self.SendRequest('live/' + str(broadcastId) + '/add_to_post_live/', self.generateSignature(data))

    def buildBody(self, bodies, boundary):
        body = u''
        for b in bodies:
            body += u'--{boundary}\r\n'.format(boundary=boundary)
            body += u'Content-Disposition: {b_type}; name="{b_name}"'.format(b_type=b['type'], b_name=b['name'])
            _filename = b.get('filename', None)
            _headers = b.get('headers', None)
            if _filename:
                _filename, ext = os.path.splitext(_filename)
                _body += u'; filename="pending_media_{uid}.{ext}"'.format(uid=self.generateUploadId(), ext=ext)
            if _headers and isinstance(_headers, list):
                for h in _headers:
                    _body += u'\r\n{header}'.format(header=h)
            body += u'\r\n\r\n{data}\r\n'.format(data=b['data'])
        body += u'--{boundary}--'.format(boundary=boundary)
        return body

    def SendRequest(self, endpoint, post=None, login=False):
        verify = False  # don't show request warning

        if (not self.isLoggedIn and not login):
            raise Exception("Not logged in!\n")

        self.s.headers.update({'Connection': 'close',
                               'Accept': '*/*',
                               'Content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
                               'Cookie2': '$Version=1',
                               'Accept-Language': 'en-US',
                               'User-Agent': self.USER_AGENT})

        while True:
            try:
                if (post is not None):
                    response = self.s.post(self.API_URL + endpoint, data=post, verify=verify)
                else:
                    response = self.s.get(self.API_URL + endpoint, verify=verify)
                break
            except Exception as e:
                print('Except on SendRequest (wait 60 sec and resend): ' + str(e))
                time.sleep(60)

        if response.status_code == 200:
            self.LastResponse = response
            self.LastJson = json.loads(response.text)
            return True
        else:
            print("Request return " + str(response.status_code) + " error!")
            # for debugging
            try:
                self.LastResponse = response
                self.LastJson = json.loads(response.text)
                print(self.LastJson)
                if 'error_type' in self.LastJson and self.LastJson['error_type'] == 'sentry_block':
                    raise SentryBlockException(self.LastJson['message'])
            except SentryBlockException:
                raise
            except:
                pass
            return False

    def getTotalFollowers(self, usernameId):
        followers = []
        next_max_id = ''
        while 1:
            self.getUserFollowers(usernameId, next_max_id)
            temp = self.LastJson

            for item in temp["users"]:
                followers.append(item)

            if temp["big_list"] is False:
                return followers
            next_max_id = temp["next_max_id"]

    def getTotalFollowings(self, usernameId):
        followers = []
        next_max_id = ''
        while True:
            self.getUserFollowings(usernameId, next_max_id)
            temp = self.LastJson

            for item in temp["users"]:
                followers.append(item)

            if temp["big_list"] is False:
                return followers
            next_max_id = temp["next_max_id"]

    def getTotalUserFeed(self, usernameId, minTimestamp=None):
        user_feed = []
        next_max_id = ''
        while True:
            self.getUserFeed(usernameId, next_max_id, minTimestamp)
            temp = self.LastJson
            for item in temp["items"]:
                user_feed.append(item)
            if temp["more_available"] is False:
                return user_feed
            next_max_id = temp["next_max_id"]

    def getTotalSelfUserFeed(self, minTimestamp=None):
        return self.getTotalUserFeed(self.username_id, minTimestamp)

    def getTotalSelfFollowers(self):
        return self.getTotalFollowers(self.username_id)

    def getTotalSelfFollowings(self):
        return self.getTotalFollowings(self.username_id)

    def getTotalLikedMedia(self, scan_rate=1):
        next_id = ''
        liked_items = []
        for x in range(0, scan_rate):
            temp = self.getLikedMedia(next_id)
            temp = self.LastJson
            try:
                next_id = temp["next_max_id"]
                for item in temp["items"]:
                    liked_items.append(item)
            except KeyError as e:
                break
        return liked_items
