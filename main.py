import os
import requests
import json
import glob
import argparse
import sys
import re
import time
import asyncio
import json
from tqdm import tqdm
from requests.exceptions import ConnectionError as conn_error
from sanitize import sanitize, slugify, SLUG_OK
from datetime import datetime
import subprocess
import yt_dlp

home_dir = os.getcwd()
download_dir = os.path.join(os.getcwd(), "out_dir")
working_dir = os.path.join(os.getcwd(), "working_dir")
HEADERS = {
    "Origin": "https://pluto.tv",
    "Referer": "https://pluto.tv",
    "User-Agent":
    "Mozilla/5.0 (Windows NT 6.3; Win64; x64; rv:85.0) Gecko/20100101 Firefox/85.0",
    "Accept": "*/*",
    "Accept-Encoding": None,
}
APP_VERSION = "5.100.1-a00ab03870075931f7b7df1e50eec1e31332ab4d"
BOOT_URL = "https://boot.pluto.tv/v4/start?appName={app_name}&appVersion={app_version}&deviceVersion={device_version}&deviceModel={device_model}&deviceMake={device_make}&deviceType={device_type}&clientID={client_id}&clientModelNumber={client_model_number}&channelID={channel_id}&serverSideAds=false&clientTime={client_time}"
STITCHER_URL = "https://service-stitcher.clusters.pluto.tv{path}?{stitcher_params}"
SEASONS_URL = "https://service-vod.clusters.pluto.tv/v4/vod/series/{series_id}/seasons?offset=1000&page=1"


class Pluto:
    def __init__(self, client_id, channel_id, series_id):
        self.session = Session()
        self.stitcher_params = None
        self.client_id = client_id
        self.channel_id = channel_id
        self.series_id = series_id

    def set_authdata(self, auth_data):
        session_token = auth_data.get("sessionToken")
        stitcher_params = auth_data.get("stitcherParams")

        self.stitcher_params = stitcher_params
        self.session._set_auth_headers(session_token)

    def fetch_authdata(self):
        print("Fetching boot data...")
        client_time = datetime.utcnow().isoformat() + "Z"
        url = BOOT_URL.format(app_name="web", app_version=APP_VERSION, device_version="89.0.0", device_model="web", device_make="firefox",
                              device_type="web", client_id=self.client_id, client_model_number="1.0.0", channel_id=self.channel_id, client_time=client_time)
        try:
            resp = self.session._get(url)
        except conn_error as error:
            print(f"Pluto Says: Connection error, {error}")
            time.sleep(0.8)
            sys.exit(0)
        else:
            print("Boot data received")
            return resp.json()

    def fetch_seasons(self):
        print("Fetching seasons...")
        client_time = datetime.utcnow().isoformat() + "Z"
        url = SEASONS_URL.format(
            series_id=self.series_id)
        try:
            resp = self.session._get(url)
        except conn_error as error:
            print(f"Pluto Says: Connection error, {error}")
            time.sleep(0.8)
            sys.exit(0)
        else:
            print("Seasons received")
            return resp.json()


class Session(object):
    def __init__(self):
        self._headers = HEADERS
        self._session = requests.sessions.Session()

    def _set_auth_headers(self, session_token=""):
        self._headers["Authorization"] = "Bearer {}".format(session_token)

    def _get(self, url):
        session = self._session.get(url, headers=self._headers)
        if session.ok:
            return session
        if not session.ok:
            raise Exception(f"{session.status_code} {session.reason}")

    def _post(self, url, data, redirect=True):
        session = self._session.post(url,
                                     data,
                                     headers=self._headers,
                                     allow_redirects=redirect)
        if session.ok:
            return session
        if not session.ok:
            raise Exception(f"{session.status_code} {session.reason}")

    def terminate(self):
        self._set_auth_headers()
        return


if not os.path.exists(download_dir):
    os.makedirs(download_dir)


def download(url, output_path, file_name, season_dir):
    os.chdir(season_dir)
    print("Downloading Episode...")
    ret_code = subprocess.Popen([
        "yt-dlp", "--force-generic-extractor", "--downloader",
        "aria2c", "-o", f"{file_name}.%(ext)s", f"{url}"
    ]).wait()
    print("Episode Downloaded")

    print("Return code: " + str(ret_code))
    if ret_code != 0:
        print("Return code from the downloader was non-0 (error), skipping!")
        return
    os.chdir(home_dir)


def check_for_aria():
    try:
        subprocess.Popen(["aria2c", "-v"],
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL).wait()
        return True
    except FileNotFoundError:
        return False
    except Exception as e:
        print(
            "> Unexpected exception while checking for Aria2c, please tell the program author about this! ",
            e)
        return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Pluto Downloader')
    parser.add_argument("-c",
                        "--client-id",
                        dest="client_id",
                        type=str,
                        help="client id",
                        required=True)

    parser.add_argument("-i",
                        "--item-id",
                        dest="item_id",
                        type=str,
                        help="item id",
                        required=True)

    args = parser.parse_args()

    aria_ret_val = check_for_aria()
    if not aria_ret_val:
        print("> Aria2c is missing from your system or path!")
        sys.exit(1)

    # access_token = None
    # if args.bearer_token:
    #     access_token = args.bearer_token
    # else:
    #     access_token = os.getenv("UDEMY_BEARER")

    pluto = Pluto(client_id=args.client_id,
                  channel_id="5a66795ef91fef2c7031c599", series_id=args.item_id)

    authdata = pluto.fetch_authdata()
    pluto.set_authdata(authdata)

    details = pluto.fetch_seasons()
    series_name = details.get("name")
    slug = details.get("slug")
    series_dir = os.path.join(download_dir, slug)
    if not os.path.isdir(series_dir):
        os.mkdir(series_dir)

    seasons = details.get("seasons")

    for season in seasons:
        season_number = season.get("number")
        season_dir = os.path.join(series_dir, str(season_number))
        if not os.path.isdir(season_dir):
            os.mkdir(season_dir)

        episodes = season.get("episodes")

        for episode in episodes:
            episode_name = '.'.join(episode.get("name").split(" ")[1:])
            # strip the season number from the front
            episode_number = str(episode.get("number"))[2:]
            episode_filename = series_name + ".S" + str(
                season_number) + ".E" + str(episode_number) + "." + episode_name
            episode_path = os.path.join(season_dir, episode_filename + ".mp4")
            stitched = episode.get("stitched").get("path")
            url = STITCHER_URL.format(
                path=stitched, stitcher_params=pluto.stitcher_params)
            if os.path.isfile(episode_path):
                print("Episode " + episode_name +
                      " is already downloaded, skipping...")
                continue
            download(url, episode_path, episode_filename, season_dir)
