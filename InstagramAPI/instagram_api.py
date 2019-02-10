#!/usr/bin/env python
# -*- coding: utf-8 -*-

import calendar
import copy
from datetime import datetime
import hashlib
import hmac
import json
import logging
import math
import os
import time
import urllib.parse
import uuid

import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning
from requests_toolbelt import MultipartEncoder

from .ImageUtils import getImageSize
from .exceptions import (
    SentryBlockException,
    NoLoginException
)

# Turn off InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

try:
    from moviepy.editor import VideoFileClip
except ImportError:
    print("Failed to import moviepy. Need only for Video upload.")

logging.basicConfig(filename='instagram_log.log', level=logging.INFO)

__all__ = ["InstagramAPI"]

class InstagramAPI:
    API_URL = 'https://i.instagram.com/api/v1/'
    DEVICE_SETTINGS = {
        'manufacturer': 'Xiaomi',
        'model': 'HM 1SW',
        'android_version': 18,
        'android_release': '4.3'
    }
    USER_AGENT = (
        'Instagram 10.26.0 Android ({android_version}/{android_release}; '
        '320dpi; '
        '720x1280; '
        '{manufacturer}; '
        '{model}; '
        'armani; '
        'qcom; '
        'en_US)'
    ).format(**DEVICE_SETTINGS)
    IG_SIG_KEY = '4f8732eb9ba7d1c8e8897a75d6474d4eb3f5279137431b2aafb71fafe2abe178'
    with open(r"InstagramAPI\EXPERIMENTS.txt", mode='r') as experiments:
        EXPERIMENTS = experiments.read()
    SIG_KEY_VERSION = '4'

    # username            # Instagram username
    # password            # Instagram password
    # debug               # Debug
    # uuid                # UUID
    # device_id           # Device ID
    # username_id         # Username ID
    # token               # _csrftoken
    # is_logged_in          # Session status
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
        self.device_id = self.generate_device_id(m.hexdigest())
        self.set_user(username, password)
        self.is_logged_in = False
        self.last_response = None
        self.session = requests.Session()

    def set_user(self, username: str, password: str):
        self.username = username
        self.password = password
        self.uuid = self.generate_UUID(True)

    def set_proxy(self, proxy: str) -> None:
        """
        Set proxy for all requests

        Proxy format - user:password@ip:port
        """
        proxies = {
            'http': proxy,
            'https': proxy
        }
        self.session.proxies.update(proxies)
        logging.info(f"Set proxy to {proxies}")

    def login(self, force: bool = False):
        if not self.is_logged_in or force:
            if self.send_request('si/fetch_headers/?challenge_type=signup&guid=' + self.generate_UUID(False), None, True):
                data = {
                    'phone_id': self.generate_UUID(True),
                    '_csrftoken': self.last_response.cookies['csrftoken'],
                    'username': self.username,
                    'guid': self.uuid,
                    'device_id': self.device_id,
                    'password': self.password,
                    'login_attempt_count': '0'
                }

                if self.send_request('accounts/login/', self.generate_signature(json.dumps(data)), True):
                    self.is_logged_in = True
                    self.username_id = self.last_json["logged_in_user"]["pk"]
                    self.rank_token = "%s_%s" % (self.username_id, self.uuid)
                    self.token = self.last_response.cookies["csrftoken"]

                    self.sync_features()
                    self.auto_complete_user_list()
                    self.timeline_feed()
                    self.get_v2_inbox()
                    self.get_recent_activity()
                    print("Login success!\n")
                    return True

    def sync_features(self):
        data = json.dumps({
            '_uuid': self.uuid,
            '_uid': self.username_id,
            'id': self.username_id,
            '_csrftoken': self.token,
            'experiments': self.EXPERIMENTS
        })
        return self.send_request('qe/sync/', self.generate_signature(data))

    def auto_complete_user_list(self):
        return self.send_request('friendships/autocomplete_user_list/')

    def timeline_feed(self):
        return self.send_request('feed/timeline/')

    def megaphone_log(self):
        return self.send_request('megaphone/log/')

    def expose(self):
        data = json.dumps({
            '_uuid': self.uuid,
            '_uid': self.username_id,
            'id': self.username_id,
            '_csrftoken': self.token,
            'experiment': 'ig_android_profile_contextual_feed'
        })
        return self.send_request('qe/expose/', self.generate_signature(data))

    def logout(self) -> None:
        """
        Logout of Instagram account
        """
        logout = self.send_request('accounts/logout/')

    def upload_photo(self, photo, caption=None, upload_id=None, is_sidecar=None):
        if upload_id is None:
            upload_id = str(int(time.time() * 1000))
        data = {
            'upload_id': upload_id,
            '_uuid': self.uuid,
            '_csrftoken': self.token,
            'image_compression': '{"lib_name":"jt","lib_version":"1.3.0","quality":"87"}',
            'photo': (
                'pending_media_%s.jpg' % upload_id,
                open(photo, 'rb'),
                'application/octet-stream',
                {'Content-Transfer-Encoding': 'binary'}
            )
        }
        if is_sidecar:
            data['is_sidecar'] = '1'
        m = MultipartEncoder(data, boundary=self.uuid)
        self.session.headers.update({
            'X-IG-Capabilities': '3Q4=',
            'X-IG-Connection-Type': 'WIFI',
            'Cookie2': '$Version=1',
            'Accept-Language': 'en-US',
            'Accept-Encoding': 'gzip, deflate',
            'Content-type': m.content_type,
            'Connection': 'close',
            'User-Agent': self.USER_AGENT
        })
        response = self.session.post(self.API_URL + "upload/photo/", data=m.to_string())
        if response.status_code == 200:
            if self.configure(upload_id, photo, caption):
                self.expose()
        return False

    def upload_video(self, video, thumbnail, caption=None, upload_id=None, is_sidecar=None):
        if upload_id is None:
            upload_id = str(int(time.time() * 1000))
        data = {
            'upload_id': upload_id,
            '_csrftoken': self.token,
            'media_type': '2',
            '_uuid': self.uuid
        }
        if is_sidecar:
            data['is_sidecar'] = '1'
        m = MultipartEncoder(data, boundary=self.uuid)
        self.session.headers.update({
            'X-IG-Capabilities': '3Q4=',
            'X-IG-Connection-Type': 'WIFI',
            'Host': 'i.instagram.com',
            'Cookie2': '$Version=1',
            'Accept-Language': 'en-US',
            'Accept-Encoding': 'gzip, deflate',
            'Content-type': m.content_type,
            'Connection': 'keep-alive',
            'User-Agent': self.USER_AGENT
        })
        response = self.session.post(self.API_URL + "upload/video/", data=m.to_string())
        if response.status_code == 200:
            body = json.loads(response.text)
            upload_url = body['video_upload_urls'][3]['url']
            upload_job = body['video_upload_urls'][3]['job']

            video_data = open(video, 'rb').read()
            # solve issue #85 TypeError: slice indices must be integers or None or have an __index__ method
            request_size = int(math.floor(len(video_data) / 4))
            last_request_extra = (len(video_data) - (request_size * 3))

            headers = copy.deepcopy(self.session.headers)
            self.session.headers.update({
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
                    end = i * request_size + last_request_extra
                else:
                    end = (i + 1) * request_size
                length = last_request_extra if i == 3 else request_size
                content_range = f"bytes {start}-{end - 1}/{len(video_data)}"

                self.session.headers.update({
                    'Content-Length': str(end - start),
                    'Content-Range': content_range
                })
                response = self.session.post(upload_url, data=video_data[start:start + length])
            self.session.headers = headers

            if response.status_code == 200:
                if self.configure_video(upload_id, video, thumbnail, caption):
                    self.expose()
        return False

    def upload_album(self, media, caption=None, upload_id=None):
        if not media:
            raise Exception("List of media to upload can't be empty.")

        if len(media) < 2 or len(media) > 10:
            raise Exception('Instagram requires that albums contain 2-10 items.'
                            f' You tried to submit {len(media)}.')

        # Figure out the media file details for ALL media in the album.
        # NOTE: We do this first, since it validates whether the media files are
        # valid and lets us avoid wasting time uploading totally invalid albums!
        for idx, item in enumerate(media):
            if not item.get('file', '') or item.get('tipe', ''):
                raise Exception(f'Media at index "{idx}" does not have the required "file" and "type" keys')


            # $itemInternalMetadata = new InternalMetadata();
            # If usertags are provided, verify that the entries are valid.
            if item.get('usertags', []):
                self.throw_if_invalid_usertags(item['usertags'])

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
                raise Exception(f'Unsupported album media type {item_type}')

            itemInternalMetadata = {}
            item['internalMetadata'] = itemInternalMetadata

        # Perform all media file uploads.
        for idx, item in enumerate(media):
            itemInternalMetadata = item['internalMetadata']
            item_upload_id = self.generate_upload_id()
            if item.get('type', '') == 'photo':
                self.upload_photo(item['file'], caption=caption, is_sidecar=True, upload_id=item_upload_id)
                # $itemInternalMetadata->setPhotoUploadResponse($this->ig->internal->upload_photoData(Constants::FEED_TIMELINE_ALBUM, $itemInternalMetadata));

            elif item.get('type', '') == 'video':
                # Attempt to upload the video data.
                self.upload_video(item['file'], item['thumbnail'], caption=caption, is_sidecar=True, upload_id=item_upload_id)
                # $itemInternalMetadata = $this->ig->internal->upload_video(Constants::FEED_TIMELINE_ALBUM, $item['file'], $itemInternalMetadata);
                # Attempt to upload the thumbnail, associated with our video's ID.
                # $itemInternalMetadata->setPhotoUploadResponse($this->ig->internal->upload_photoData(Constants::FEED_TIMELINE_ALBUM, $itemInternalMetadata));
                pass
            item['internalMetadata']['upload_id'] = item_upload_id

        albumInternalMetadata = {}
        return self.configure_timeline_album(media, albumInternalMetadata, caption_text=caption)

    def throw_if_invalid_usertags(self, usertags):
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

    def configure_timeline_album(self, media, albumInternalMetadata, caption_text='', location=None):
        endpoint = 'media/configure_sidecar/'
        albumUploadId = self.generate_upload_id()

        date = datetime.utcnow().isoformat()
        children_metadata = []
        for item in media:
            itemInternalMetadata = item['internalMetadata']
            uploadId = itemInternalMetadata.get('upload_id', self.generate_upload_id())
            if item.get('type', '') == 'photo':
                # Build this item's configuration.
                photo_config = {
                    'date_time_original': date,
                    'scene_type': 1,
                    'disable_comments': False,
                    'upload_id': uploadId,
                    'source_type': 0,
                    'scene_capture_type': 'standard',
                    'date_time_digitized': date,
                    'geotag_enabled': False,
                    'camera_position': 'back',
                    'edits': {
                        'filter_strength': 1,
                        'filter_name': 'IGNormalFilter'
                    }
                }
                # This usertag per-file EXTERNAL metadata is only supported for PHOTOS!
                if item.get('usertags', []):
                    # NOTE: These usertags were validated in Timeline::uploadAlbum.
                    photo_config['usertags'] = json.dumps({'in': item['usertags']})

                children_metadata.append(photo_config)
            if item.get('type', '') == 'video':
                # Get all of the INTERNAL per-VIDEO metadata.
                video_details = itemInternalMetadata.get('video_details', {})
                # Build this item's configuration.
                video_config = {
                    'length': video_details.get('duration', 1.0),
                    'date_time_original': date,
                    'scene_type': 1,
                    'poster_frame_index': 0,
                    'trim_type': 0,
                    'disable_comments': False,
                    'upload_id': uploadId,
                    'source_type': 'library',
                    'geotag_enabled': False,
                    'edits': {
                        'length': video_details.get('duration', 1.0),
                        'cinema': 'unsupported',
                        'original_length': video_details.get('duration', 1.0),
                        'source_type': 'library',
                        'start_time': 0,
                        'camera_position': 'unknown',
                        'trim_type': 0
                    }
                }

                children_metadata.append(video_config)
        # Build the request...
        data = {
            '_csrftoken': self.token,
            '_uid': self.username_id,
            '_uuid': self.uuid,
            'client_sidecar_id': albumUploadId,
            'caption': caption_text,
            'children_metadata': children_metadata
        }
        self.send_request(endpoint, self.generate_signature(json.dumps(data)))
        response = self.last_response
        if response.status_code == 200:
            self.last_response = response
            self.last_json = json.loads(response.text)
            return True
        else:
            print("Request return " + str(response.status_code) + " error!")
            # for debugging
            self.last_response = response
            self.last_json = json.loads(response.text)
            return False

    def direct_message(self, text, recipients):
        if type(recipients) != type([]):
            recipients = [str(recipients)]
        recipient_users = '"",""'.join(str(r) for r in recipients)
        endpoint = 'direct_v2/threads/broadcast/text/'
        boundary = self.uuid
        bodies = [
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
        data = self.build_body(bodies, boundary)
        self.session.headers.update({
            'User-Agent': self.USER_AGENT,
            'Proxy-Connection': 'keep-alive',
            'Connection': 'keep-alive',
            'Accept': '*/*',
            'Content-Type': 'multipart/form-data; boundary={}'.format(boundary),
            'Accept-Language': 'en-en'
        })
        #self.send_request(endpoint,post=data) #overwrites 'Content-type' header and boundary is missed
        response = self.session.post(self.API_URL + endpoint, data=data)

        if response.status_code == 200:
            self.last_response = response
            self.last_json = json.loads(response.text)
            return True
        else:
            print ("Request return " + str(response.status_code) + " error!")
            # for debugging
            try:
                self.last_response = response
                self.last_json = json.loads(response.text)
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
        data = self.build_body(bodies, boundary)
        self.session.headers.update({
            'User-Agent': self.USER_AGENT,
            'Proxy-Connection': 'keep-alive',
            'Connection': 'keep-alive',
            'Accept': '*/*',
            'Content-Type': 'multipart/form-data; boundary={}'.format(boundary),
            'Accept-Language': 'en-en'
        })
        # self.send_request(endpoint,post=data) #overwrites 'Content-type' header and boundary is missed
        response = self.session.post(self.API_URL + endpoint, data=data)

        if response.status_code == 200:
            self.last_response = response
            self.last_json = json.loads(response.text)
            return True
        else:
            print("Request return " + str(response.status_code) + " error!")
            # for debugging
            try:
                self.last_response = response
                self.last_json = json.loads(response.text)
            except:
                pass
            return False

    def configure_video(self, upload_id, video, thumbnail, caption=''):
        clip = VideoFileClip(video)
        self.upload_photo(photo=thumbnail, caption=caption, upload_id=upload_id)
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
        return self.send_request('media/configure/?video=1', self.generate_signature(data))

    def configure(self, upload_id, photo, caption=''):
        (w, h) = getImageSize(photo)
        data = json.dumps({
            '_csrftoken': self.token,
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
            }
        })
        return self.send_request('media/configure/?', self.generate_signature(data))

    def edit_media(self, media_id, caption_text=''):
        data = json.dumps({
            '_uuid': self.uuid,
            '_uid': self.username_id,
            '_csrftoken': self.token,
            'caption_text': caption_text
        })
        return self.send_request('media/' + str(media_id) + '/edit_media/', self.generate_signature(data))

    def remove_self_tag(self, media_id):
        data = json.dumps({
            '_uuid': self.uuid,
            '_uid': self.username_id,
            '_csrftoken': self.token
        })
        return self.send_request('media/' + str(media_id) + '/remove/', self.generate_signature(data))

    def media_info(self, media_id):
        data = json.dumps({
            '_uuid': self.uuid,
            '_uid': self.username_id,
            '_csrftoken': self.token,
            'media_id': media_id
        })
        return self.send_request('media/' + str(media_id) + '/info/', self.generate_signature(data))

    def delete_media(self, media_id, media_type=1):
        data = json.dumps({
            '_uuid': self.uuid,
            '_uid': self.username_id,
            '_csrftoken': self.token,
            'media_type': media_type,
            'media_id': media_id
        })
        return self.send_request('media/' + str(media_id) + '/delete/', self.generate_signature(data))

    def change_password(self, new_password):
        data = json.dumps({
            '_uuid': self.uuid,
            '_uid': self.username_id,
            '_csrftoken': self.token,
            'old_password': self.password,
            'new_password1': new_password,
            'new_password2': new_password
        })
        return self.send_request('accounts/change_password/', self.generate_signature(data))

    def explore(self):
        return self.send_request('discover/explore/')

    def comment(self, media_id, comment_text):
        data = json.dumps({
            '_uuid': self.uuid,
            '_uid': self.username_id,
            '_csrftoken': self.token,
            'comment_text': comment_text
        })
        return self.send_request('media/' + str(media_id) + '/comment/', self.generate_signature(data))

    def delete_comment(self, media_id, comment_id):
        data = json.dumps({
            '_uuid': self.uuid,
            '_uid': self.username_id,
            '_csrftoken': self.token
        })
        return self.send_request('media/' + str(media_id) + '/comment/' + str(comment_id) + '/delete/', self.generate_signature(data))

    def change_profile_picture(self, photo):
        # TODO Instagram.php 705-775
        return False

    def remove_profile_picture(self):
        data = json.dumps({
            '_uuid': self.uuid,
            '_uid': self.username_id,
            '_csrftoken': self.token
        })
        return self.send_request('accounts/remove_profile_picture/', self.generate_signature(data))

    def set_private_account(self):
        data = json.dumps({
            '_uuid': self.uuid,
            '_uid': self.username_id,
            '_csrftoken': self.token
        })
        return self.send_request('accounts/set_private/', self.generate_signature(data))

    def set_public_account(self):
        data = json.dumps({
            '_uuid': self.uuid,
            '_uid': self.username_id,
            '_csrftoken': self.token
        })
        return self.send_request('accounts/set_public/', self.generate_signature(data))

    def get_profile_data(self):
        data = json.dumps({
            '_uuid': self.uuid,
            '_uid': self.username_id,
            '_csrftoken': self.token
        })
        return self.send_request('accounts/current_user/?edit=true', self.generate_signature(data))

    def edit_profile(self, url, phone, first_name, biography, email, gender):
        data = json.dumps({
            '_uuid': self.uuid,
            '_uid': self.username_id,
            '_csrftoken': self.token,
            'external_url': url,
            'phone_number': phone,
            'username': self.username,
            'full_name': first_name,
            'biography': biography,
            'email': email,
            'gender': gender
        })
        return self.send_request('accounts/edit_profile/', self.generate_signature(data))

    def get_story(self, username_id):
        return self.send_request('feed/user/' + str(username_id) + '/reel_media/')

    def get_username_info(self, username_id):
        return self.send_request('users/' + str(username_id) + '/info/')

    def get_self_username_info(self):
        return self.get_username_info(self.username_id)

    def get_self_saved_media(self):
        return self.send_request('feed/saved')

    def get_recent_activity(self):
        activity = self.send_request('news/inbox/?')
        return activity

    def get_following_recent_activity(self):
        activity = self.send_request('news/?')
        return activity

    def get_v2_inbox(self):
        inbox = self.send_request('direct_v2/inbox/?')
        return inbox

    def get_v2_threads(self, thread, cursor=None):
        endpoint = 'direct_v2/threads/{0}'.format(thread)
        if cursor is not None:
            endpoint += '?cursor={0}'.format(cursor)
        inbox = self.send_request(endpoint)
        return inbox

    def get_user_tags(self, username_id):
        tags = self.send_request('usertags/' + str(username_id) + '/feed/?rank_token=' + str(self.rank_token) + '&ranked_content=true&')
        return tags

    def get_self_user_tags(self):
        return self.get_user_tags(self.username_id)

    def tag_feed(self, tag):
        user_feed = self.send_request('feed/tag/' + str(tag) + '/?rank_token=' + str(self.rank_token) + '&ranked_content=true&')
        return user_feed

    def get_media_likers(self, media_id):
        likers = self.send_request('media/' + str(media_id) + '/likers/?')
        return likers

    def get_geo_media(self, username_id):
        locations = self.send_request('maps/user/' + str(username_id) + '/')
        return locations

    def get_self_geo_media(self):
        return self.get_geo_media(self.username_id)

    def fb_user_search(self, query):
        query = self.send_request('fbsearch/topsearch/?context=blended&query=' + str(query) + '&rank_token=' + str(self.rank_token))
        return query

    def search_users(self, query):
        query = self.send_request('users/search/?ig_sig_key_version=' + str(self.SIG_KEY_VERSION) + '&is_typeahead=true&query=' + str(query) + '&rank_token=' + str(self.rank_token))
        return query

    def search_username(self, username):
        return self.send_request(f'users/{str(username)}/usernameinfo/')

    def sync_from_adress_book(self, contacts):
        return self.send_request('address_book/link/?include=extra_display_name,thumbnails', "contacts=" + json.dumps(contacts))

    def search_tags(self, query):
        query = self.send_request('tags/search/?is_typeahead=true&q=' + str(query) + '&rank_token=' + str(self.rank_token))
        return query

    def get_timeline(self):
        query = self.send_request('feed/timeline/?rank_token=' + str(self.rank_token) + '&ranked_content=true&')
        return query

    def get_user_feed(self, username_id, maxid='', min_timestamp=None):
        query = self.send_request('feed/user/%s/?max_id=%s&min_timestamp=%s&rank_token=%s&ranked_content=true'
                                 % (username_id, maxid, min_timestamp, self.rank_token))
        return query

    def get_self_user_feed(self, maxid='', min_timestamp=None):
        return self.get_user_feed(self.username_id, maxid, min_timestamp)

    def get_hashtag_feed(self, hashtag: str, maxid=''):
        return self.send_request(f'feed/tag/{hashtag}/?max_id=' + str(maxid) + '&rank_token=' + self.rank_token + '&ranked_content=true&')

    def search_location(self, query):
        location_feed = self.send_request('fbsearch/places/?rank_token=' + str(self.rank_token) + '&query=' + str(query))
        return location_feed

    def get_location_feed(self, location_id, maxid=''):
        return self.send_request('feed/location/' + str(location_id) + '/?max_id=' + maxid + '&rank_token=' + self.rank_token + '&ranked_content=true&')

    def get_popular_feed(self):
        popular_feed = self.send_request('feed/popular/?people_teaser_supported=1&rank_token=' + str(self.rank_token) + '&ranked_content=true&')
        return popular_feed

    def get_user_followings(self, username_id, maxid=''):
        url = 'friendships/' + str(username_id) + '/following/?'
        query_string = {
            'ig_sig_key_version': self.SIG_KEY_VERSION,
            'rank_token': self.rank_token
        }
        if maxid:
            query_string['max_id'] = maxid
        url += urllib.parse.urlencode(query_string)
        return self.send_request(url)

    def get_self_users_following(self):
        return self.get_user_followings(self.username_id)

    def get_user_followers(self, username_id, maxid=''):
        if maxid == '':
            return self.send_request('friendships/' + str(username_id) + '/followers/?rank_token=' + self.rank_token)
        else:
            return self.send_request('friendships/' + str(username_id) + '/followers/?rank_token=' + self.rank_token + '&max_id=' + str(maxid))

    def get_self_user_followers(self):
        return self.get_user_followers(self.username_id)

    def get_pending_follow_requests(self):
        return self.send_request('friendships/pending?')

    def like(self, media_id):
        data = json.dumps({
            '_uuid': self.uuid,
            '_uid': self.username_id,
            '_csrftoken': self.token,
            'media_id': media_id
        })
        return self.send_request('media/' + str(media_id) + '/like/', self.generate_signature(data))

    def unlike(self, media_id):
        data = json.dumps({
            '_uuid': self.uuid,
            '_uid': self.username_id,
            '_csrftoken': self.token,
            'media_id': media_id
        })
        return self.send_request('media/' + str(media_id) + '/unlike/', self.generate_signature(data))

    def save(self, media_id):
        data = json.dumps({
            '_uuid': self.uuid,
            '_uid': self.username_id,
            '_csrftoken': self.token,
            'media_id': media_id
        })
        return self.send_request('media/' + str(media_id) + '/save/', self.generate_signature(data))

    def unsave(self, media_id):
        data = json.dumps({
            '_uuid': self.uuid,
            '_uid': self.username_id,
            '_csrftoken': self.token,
            'media_id': media_id
        })
        return self.send_request('media/' + str(media_id) + '/unsave/', self.generate_signature(data))

    def get_media_comments(self, media_id, max_id=''):
        return self.send_request('media/' + media_id + '/comments/?max_id=' + max_id)

    def set_name_and_phone(self, name='', phone=''):
        data = json.dumps({
            '_uuid': self.uuid,
            '_uid': self.username_id,
            'first_name': name,
            'phone_number': phone,
            '_csrftoken': self.token
        })
        return self.send_request('accounts/set_phone_and_name/', self.generate_signature(data))

    def get_direct_share(self):
        return self.send_request('direct_share/inbox/?')

    def backup(self):
        # TODO Instagram.php 1470-1485
        return False

    def approve(self, user_id):
        data = json.dumps({
            '_uuid': self.uuid,
            '_uid': self.username_id,
            'user_id': user_id,
            '_csrftoken': self.token
        })
        return self.send_request('friendships/approve/'+ str(user_id) + '/', self.generate_signature(data))

    def ignore(self, user_id):
        data = json.dumps({
            '_uuid': self.uuid,
            '_uid': self.username_id,
            'user_id': user_id,
            '_csrftoken': self.token
        })
        return self.send_request('friendships/ignore/'+ str(user_id) + '/', self.generate_signature(data))

    def follow(self, user_id):
        data = json.dumps({
            '_uuid': self.uuid,
            '_uid': self.username_id,
            'user_id': user_id,
            '_csrftoken': self.token
        })
        return self.send_request('friendships/create/' + str(user_id) + '/', self.generate_signature(data))

    def unfollow(self, user_id):
        data = json.dumps({
            '_uuid': self.uuid,
            '_uid': self.username_id,
            'user_id': user_id,
            '_csrftoken': self.token
        })
        return self.send_request('friendships/destroy/' + str(user_id) + '/', self.generate_signature(data))

    def block(self, user_id):
        data = json.dumps({
            '_uuid': self.uuid,
            '_uid': self.username_id,
            'user_id': user_id,
            '_csrftoken': self.token
        })
        return self.send_request('friendships/block/' + str(user_id) + '/', self.generate_signature(data))

    def unblock(self, user_id):
        data = json.dumps({
            '_uuid': self.uuid,
            '_uid': self.username_id,
            'user_id': user_id,
            '_csrftoken': self.token
        })
        return self.send_request('friendships/unblock/' + str(user_id) + '/', self.generate_signature(data))

    def user_friendship(self, user_id):
        data = json.dumps({
            '_uuid': self.uuid,
            '_uid': self.username_id,
            'user_id': user_id,
            '_csrftoken': self.token
        })
        return self.send_request('friendships/show/' + str(user_id) + '/', self.generate_signature(data))

    def get_liked_media(self, maxid=''):
        return self.send_request('feed/liked/?max_id=' + str(maxid))

    def generate_signature(self, data):
        parsed_data = urllib.parse.quote(data)
        return f'ig_sig_key_version={self.SIG_KEY_VERSION}&signed_body=' + hmac.new(self.IG_SIG_KEY.encode('utf-8'), data.encode('utf-8'), hashlib.sha256).hexdigest() + '.' + parsed_data

    def generate_device_id(self, seed):
        volatile_seed = "12345"
        m = hashlib.md5()
        m.update(seed.encode('utf-8') + volatile_seed.encode('utf-8'))
        return 'android-' + m.hexdigest()[:16]

    def generate_UUID(self, type):
        generated_uuid = str(uuid.uuid4())
        if type:
            return generated_uuid
        else:
            return generated_uuid.replace('-', '')

    def generate_upload_id(self):
        return str(calendar.timegm(datetime.utcnow().utctimetuple()))

    def create_broadcast(self, preview_width=1080, preview_height=1920, broadcast_message=''):
        data = json.dumps({
            '_uuid': self.uuid,
            '_uid': self.username_id,
            'preview_height': preview_height,
            'preview_width': preview_width,
            'broadcast_message': broadcast_message,
            'broadcast_type': 'RTMP',
            'internal_only': 0,
            '_csrftoken': self.token
        })
        return self.send_request('live/create/', self.generate_signature(data))

    def start_broadcast(self, broadcast_id, send_notification=False):
        data = json.dumps({
            '_uuid': self.uuid,
            '_uid': self.username_id,
            'should_send_notifications': int(send_notification),
            '_csrftoken': self.token
        })
        return self.send_request('live/' + str(broadcast_id) + '/start', self.generate_signature(data))

    def stop_broadcast(self, broadcast_id):
        data = json.dumps({
            '_uuid': self.uuid,
            '_uid': self.username_id,
            '_csrftoken': self.token
        })
        return self.send_request('live/' + str(broadcast_id) + '/end_broadcast/', self.generate_signature(data))

    def add_broadcast_to_live(self, broadcast_id):
        # broadcast has to be ended first!
        data = json.dumps({
            '_uuid': self.uuid,
            '_uid': self.username_id,
            '_csrftoken': self.token
        })
        return self.send_request('live/' + str(broadcast_id) + '/add_to_post_live/', self.generate_signature(data))

    def build_body(self, bodies, boundary):
        body = u''
        for b in bodies:
            body += u'--{boundary}\r\n'.format(boundary=boundary)
            body += u'Content-Disposition: {b_type}; name="{b_name}"'.format(b_type=b['type'], b_name=b['name'])
            _filename = b.get('filename', None)
            _headers = b.get('headers', None)
            if _filename:
                _filename, ext = os.path.splitext(_filename)
                _body += u'; filename="pending_media_{uid}.{ext}"'.format(uid=self.generate_upload_id(), ext=ext)
            if _headers and isinstance(_headers, list):
                for h in _headers:
                    _body += u'\r\n{header}'.format(header=h)
            body += u'\r\n\r\n{data}\r\n'.format(data=b['data'])
        body += u'--{boundary}--'.format(boundary=boundary)
        return body

    def send_request(self, endpoint: str, post=None, login=False):
        verify = False  # don't show request warning

        if not self.is_logged_in:
            raise NoLoginException("You are not currently logged in. "
                                   "Try running InstagramAPI.login()")

        self.session.headers.update({
            'Connection': 'close',
            'Accept': '*/*',
            'Content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'Cookie2': '$Version=1',
            'Accept-Language': 'en-US',
            'User-Agent': self.USER_AGENT
        })

        while True:
            try:
                if post is not None:
                    response = self.session.post(self.API_URL + endpoint, data=post, verify=verify)
                else:
                    response = self.session.get(self.API_URL + endpoint, verify=verify)
                break
            except Exception as e:
                print('Except on send_request (wait 60 sec and resend): ' + str(e))
                time.sleep(60)

        if response.status_code == 200:
            self.last_response = response
            self.last_json = json.loads(response.text)
            return True
        else:
            print("Request return " + str(response.status_code) + " error!")
            # for debugging
            try:
                self.last_response = response
                self.last_json = json.loads(response.text)
                print(self.last_json)
                if 'error_type' in self.last_json and self.last_json['error_type'] == 'sentry_block':
                    raise SentryBlockException(self.last_json['message'])
            except SentryBlockException:
                raise
            except:
                pass
            return False

    def get_total_followers(self, username_id):
        followers = []
        next_max_id = ''
        while 1:
            self.get_user_followers(username_id, next_max_id)
            temp = self.last_json

            for item in temp["users"]:
                followers.append(item)

            if temp["big_list"] is False:
                return followers
            next_max_id = temp["next_max_id"]

    def get_total_followings(self, username_id):
        followers = []
        next_max_id = ''
        while True:
            self.get_user_followings(username_id, next_max_id)
            temp = self.last_json

            for item in temp["users"]:
                followers.append(item)

            if temp["big_list"] is False:
                return followers
            next_max_id = temp["next_max_id"]

    def get_total_user_feed(self, username_id, min_timestamp=None):
        user_feed = []
        next_max_id = ''
        while True:
            self.get_user_feed(username_id, next_max_id, min_timestamp)
            temp = self.last_json
            for item in temp["items"]:
                user_feed.append(item)
            if temp["more_available"] is False:
                return user_feed
            next_max_id = temp["next_max_id"]

    def get_total_self_user_feed(self, min_timestamp=None):
        return self.get_total_user_feed(self.username_id, min_timestamp)

    def get_total_self_followers(self):
        return self.get_total_followers(self.username_id)

    def get_total_self_followings(self):
        return self.get_total_followings(self.username_id)

    def get_total_liked_media(self, scan_rate=1):
        next_id = ''
        liked_items = []
        for x in range(0, scan_rate):
            temp = self.get_liked_media(next_id)
            temp = self.last_json
            try:
                next_id = temp["next_max_id"]
                for item in temp["items"]:
                    liked_items.append(item)
            except KeyError as e:
                break
        return liked_items
