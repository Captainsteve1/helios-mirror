from logging import getLogger, ERROR
from os import remove as osremove, walk, path as ospath, rename as osrename
from time import time, sleep
from pyrogram.errors import FloodWait, RPCError
from PIL import Image
from threading import RLock

from bot import AS_DOCUMENT, AS_DOC_USERS, AS_MEDIA_USERS, CUSTOM_FILENAME, EXTENSION_FILTER, app, app_session, BOT_PM, LEECH_LOG
from bot.helper.ext_utils.fs_utils import take_ss, get_media_info, get_media_streams, clean_unwanted
from bot.helper.ext_utils.bot_utils import get_readable_file_size

LOGGER = getLogger(__name__)
getLogger("pyrogram").setLevel(ERROR)

IMAGE_SUFFIXES = ("JPG", "JPX", "PNG", "CR2", "TIF", "BMP", "JXR", "PSD", "ICO", "HEIC", "JPEG")


class TgUploader:

    def __init__(self, name=None, path=None, size=0, listener=None):
        self.name = name
        self.uploaded_bytes = 0
        self._last_uploaded = 0
        self.__listener = listener
        self.__path = path
        self.__start_time = time()
        self.__total_files = 0
        self.__is_cancelled = False
        self.__as_doc = AS_DOCUMENT
        self.__thumb = f"Thumbnails/{listener.message.from_user.id}.jpg"
        self.__msgs_dict = {}
        self.__corrupted = 0
        self.__resource_lock = RLock()
        self.__is_corrupted = False
        self.__sent_msg = app.get_messages(self.__listener.message.chat.id, self.__listener.uid)
        self.__size = size
        self.__user_settings()
        self.isPrivate = listener.message.chat.type in ['private', 'group']
        self.__app = app
        self.__user_id = listener.message.from_user.id

    def upload(self, o_files):
        for dirpath, subdir, files in sorted(walk(self.__path)):
            for file_ in sorted(files):
                if file_ in o_files:
                    continue
                if not file_.lower().endswith(tuple(EXTENSION_FILTER)):
                    up_path = ospath.join(dirpath, file_)
                    self.__total_files += 1
                    try:
                        if ospath.getsize(up_path) == 0:
                            LOGGER.error(f"{up_path} size is zero, telegram don't upload zero size files")
                            self.__corrupted += 1
                            continue
                    except Exception as e:
                        if self.__is_cancelled:
                            return
                        else:
                            LOGGER.error(e)
                            continue
                    self.__upload_file(up_path, file_, dirpath)
                    if self.__is_cancelled:
                        return
                    if not self.__listener.isPrivate and not self.__is_corrupted:
                        self.__msgs_dict[self.__sent_msg.link] = file_
                    self._last_uploaded = 0
                    sleep(1)
        if self.__listener.seed and not self.__listener.newDir:
            clean_unwanted(self.__path)
        if self.__total_files <= self.__corrupted:
            return self.__listener.onUploadError('Files Corrupted. Check logs')
        LOGGER.info(f"Leech Completed: {self.name}")
        size = get_readable_file_size(self.__size)
        self.__listener.onUploadComplete(None, size, self.__msgs_dict, self.__total_files, self.__corrupted, self.name)

    def __upload_file(self, up_path, file_, dirpath):
        fsize = ospath.getsize(up_path)
        if fsize > 2097152000:
            client = app_session
        else:
            client = app
        if LEECH_LOG:
            set = LEECH_LOG.copy()
            setstr = str(set)[1:-1]
            LEECH_DUMP = int(setstr)
            leechchat = LEECH_DUMP
        else: leechchat = self.__listener.message.chat.id
        if CUSTOM_FILENAME is not None:
            cap_mono = f"{CUSTOM_FILENAME} <code>{file_}</code>"
            file_ = f"{CUSTOM_FILENAME} {file_}"
            new_path = ospath.join(dirpath, file_)
            osrename(up_path, new_path)
            up_path = new_path
        else:
            cap_mono = f"<code>{file_}</code>"
        notMedia = False
        thumb = self.__thumb
        self.__is_corrupted = False
        try:
            is_video, is_audio = get_media_streams(up_path)
            if not self.__as_doc:
                if is_video:
                    duration = get_media_info(up_path)[0]
                    if thumb is None:
                        thumb = take_ss(up_path, duration)
                        if self.__is_cancelled:
                            if self.__thumb is None and thumb is not None and ospath.lexists(thumb):
                                osremove(thumb)
                            return
                    if thumb is not None:
                        with Image.open(thumb) as img:
                            width, height = img.size
                    else:
                        width = 480
                        height = 320
                    if not file_.upper().endswith(("MKV", "MP4")):
                        file_ = f"{ospath.splitext(file_)[0]}.mp4"
                        new_path = ospath.join(dirpath, file_)
                        osrename(up_path, new_path)
                        up_path = new_path
                    self.__sent_msg = client.send_video(chat_id=leechchat, video=up_path,
                                                                  caption=cap_mono,
                                                                  duration=duration,
                                                                  width=width,
                                                                  height=height,
                                                                  thumb=thumb,
                                                                  supports_streaming=True,
                                                                  disable_notification=True,
                                                                  progress=self.__upload_progress)
                    if not self.isPrivate and BOT_PM:
                        try:
                            app.copy_message(chat_id=self.__user_id, from_chat_id=self.__sent_msg.chat.id, message_id=self.__sent_msg.id)
                        except Exception as err:
                                LOGGER.error(f"Failed To Send Video in PM:\n{err}")
                elif is_audio:
                    duration , artist, title = get_media_info(up_path)
                    self.__sent_msg = client.send_audio(chat_id=leechchat, audio=up_path,
                                                                  caption=cap_mono,
                                                                  duration=duration,
                                                                  performer=artist,
                                                                  title=title,
                                                                  thumb=thumb,
                                                                  disable_notification=True,
                                                                  progress=self.__upload_progress)
                    if not self.isPrivate and BOT_PM:
                        try:
                            app.copy_message(chat_id=self.__user_id, from_chat_id=self.__sent_msg.chat.id, message_id=self.__sent_msg.id)
                        except Exception as err:
                                LOGGER.error(f"Failed To Send Audio in PM:\n{err}")
                elif file_.upper().endswith(IMAGE_SUFFIXES):
                    self.__sent_msg = self.__app.send_photo(chat_id=leechchat, photo=up_path,
                                                                  caption=cap_mono,
                                                                  disable_notification=True,
                                                                  progress=self.__upload_progress)
                    if not self.isPrivate and BOT_PM:
                        try:
                            app.copy_message(chat_id=self.__user_id, from_chat_id=self.__sent_msg.chat.id, message_id=self.__sent_msg.id)
                        except Exception as err:
                                LOGGER.error(f"Failed To Send Image in PM:\n{err}")
                else:
                    notMedia = True
            if self.__as_doc or notMedia:
                if is_video and thumb is None:
                    thumb = take_ss(up_path, None)
                    if self.__is_cancelled:
                        if self.__thumb is None and thumb is not None and ospath.lexists(thumb):
                            osremove(thumb)
                        return
                self.__sent_msg = client.send_document(chat_id=leechchat, document=up_path,
                                                                 thumb=thumb,
                                                                 caption=cap_mono,
                                                                 disable_notification=True,
                                                                 progress=self.__upload_progress)
                if not self.isPrivate and BOT_PM:
                    try:
                        app.copy_message(chat_id=self.__user_id, from_chat_id=self.__sent_msg.chat.id, message_id=self.__sent_msg.id)
                    except Exception as err:
                        LOGGER.error(f"Failed To Send Document in PM:\n{err}")
        except FloodWait as f:
            LOGGER.warning(str(f))
            sleep(f.value)
        except RPCError as e:
            LOGGER.error(f"RPCError: Make Sure Leech Log chat id is correct and BOT have admin privileges in Leech log channel/group {e} Path: {up_path}")
            self.__corrupted += 1
            self.__is_corrupted = True
        except Exception as err:
            LOGGER.error(f"{err} Path: {up_path}")
            self.__corrupted += 1
            self.__is_corrupted = True
        if self.__thumb is None and thumb is not None and ospath.lexists(thumb):
            osremove(thumb)
        if not self.__is_cancelled and \
                   (not self.__listener.seed or self.__listener.newDir or dirpath.endswith("splited_files_mltb")):
            try:
                osremove(up_path)
            except:
                pass

    def __upload_progress(self, current, total):
        if self.__is_cancelled:
            app.stop_transmission()
            return
        with self.__resource_lock:
            chunk_size = current - self._last_uploaded
            self._last_uploaded = current
            self.uploaded_bytes += chunk_size

    def __user_settings(self):
        if self.__listener.message.from_user.id in AS_DOC_USERS:
            self.__as_doc = True
        elif self.__listener.message.from_user.id in AS_MEDIA_USERS:
            self.__as_doc = False
        if not ospath.lexists(self.__thumb):
            self.__thumb = None

    @property
    def speed(self):
        with self.__resource_lock:
            try:
                return self.uploaded_bytes / (time() - self.__start_time)
            except:
                return 0

    def cancel_download(self):
        self.__is_cancelled = True
        LOGGER.info(f"Cancelling Upload: {self.name}")
        self.__listener.onUploadError('your upload has been stopped!')
