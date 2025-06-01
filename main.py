import argparse
import datetime
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import m3u8
import requests
from requests.exceptions import ConnectionError as conn_error
from sanitize_filename import sanitize

home_dir = os.getcwd()
download_dir = Path(os.getcwd(), "out_dir")
working_dir = Path(os.getcwd(), "working_dir")
HEADERS = {
    "Origin": "https://pluto.tv",
    "Referer": "https://pluto.tv",
    "User-Agent": "Mozilla/5.0 (Windows NT 6.3; Win64; x64; rv:85.0) Gecko/20100101 Firefox/85.0",
    "Accept": "*/*",
    "Accept-Encoding": None,
}
APP_VERSION = "5.100.1-a00ab03870075931f7b7df1e50eec1e31332ab4d"
BOOT_URL = "https://boot.pluto.tv/v4/start?appName={app_name}&appVersion={app_version}&deviceVersion={device_version}&deviceModel={device_model}&deviceMake={device_make}&deviceType={device_type}&clientID={client_id}&clientModelNumber={client_model_number}&channelID={channel_id}&seriesIDs={item_id}&serverSideAds=false&clientTime={client_time}"
STITCHER_URL = "https://service-stitcher.clusters.pluto.tv{path}?{stitcher_params}"
SEASONS_URL = "https://service-vod.clusters.pluto.tv/v4/vod/series/{series_id}/seasons?offset=1000&page=1"
ITEMS_URL = "https://service-vod.clusters.pluto.tv/v4/vod/items?ids={item_id}"


class Pluto:
    def __init__(self, client_id, channel_id, item_id):
        self.session = Session()
        self.stitcher_params = None
        self.client_id = client_id
        self.channel_id = channel_id
        self.item_id = item_id

    def set_authdata(self, auth_data):
        session_token = auth_data.get("sessionToken")
        stitcher_params = auth_data.get("stitcherParams")

        self.stitcher_params = stitcher_params
        self.session._set_auth_headers(session_token)

    def fetch_authdata(self):
        print("Fetching boot data...")
        client_time = datetime.datetime.now(datetime.UTC)
        url = BOOT_URL.format(
            app_name="web",
            app_version=APP_VERSION,
            device_version="89.0.0",
            device_model="web",
            device_make="firefox",
            device_type="web",
            client_id=self.client_id,
            client_model_number="1.0.0",
            channel_id=self.channel_id,
            client_time=client_time,
            item_id=self.item_id,
        )
        try:
            resp = self.session._get(url)
        except conn_error as error:
            print(f"Pluto Says: Connection error, {error}")
            time.sleep(0.8)
            sys.exit(0)
        else:
            print("Boot data received")
            return resp.json()

    def fetch_items(self):
        print("Fetching items...")
        url = ITEMS_URL.format(item_id=self.item_id)
        try:
            resp = self.session._get(url)
        except conn_error as error:
            print(f"Pluto Says: Connection error, {error}")
            time.sleep(0.8)
            sys.exit(0)
        else:
            print("Items received")
            return resp.json()[0]

    def fetch_seasons(self):
        print("Fetching seasons...")
        url = SEASONS_URL.format(series_id=self.item_id)
        try:
            resp = self.session._get(url)
        except conn_error as error:
            print(f"Pluto Says: Connection error, {error}")
            time.sleep(0.8)
            sys.exit(0)
        else:
            print("Seasons received")
            return resp.json()

    def make_stitcher_url(self, url_path):
        # if not self.stitcher_url:
        #     raise Exception("Stitcher URL is not set. Fetch auth data first.")
        # url = f"{self.stitcher_url}/v2{url_path}?{self.stitcher_params}&jwt={self.session_token}&masterJWTPassthrough=true"
        # return url
        return STITCHER_URL.format(path=url_path, stitcher_params=self.stitcher_params)

    def get_best_playlist_url(self, master_playlist_url):
        manifest = m3u8.load(master_playlist_url)
        # get the best bandwidth
        best_playlist = max(manifest.playlists, key=lambda p: p.stream_info.bandwidth)
        if not best_playlist:
            return None
        path = best_playlist.uri
        base_url = master_playlist_url.rsplit("/", 1)[0]
        full_url = f"{base_url}/{path}"
        return full_url


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
        session = self._session.post(url, data, headers=self._headers, allow_redirects=redirect)
        if session.ok:
            return session
        if not session.ok:
            raise Exception(f"{session.status_code} {session.reason}")

    def terminate(self):
        self._set_auth_headers()
        return


download_dir.mkdir(parents=True, exist_ok=True)
working_dir.mkdir(parents=True, exist_ok=True)


# def download(url, file_name, season_dir):
#     os.chdir(season_dir)
#     ret_code = subprocess.Popen(
#         ["yt-dlp", "--force-generic-extractor", "--downloader", "aria2c", "-o", f"{file_name}.%(ext)s", f"{url}"]
#     ).wait()
#     print("Download Complete")

#     print("Return code: " + str(ret_code))
#     if ret_code != 0:
#         print("Return code from the downloader was non-0 (error), skipping!")
#         return
#     os.chdir(home_dir)


def download(url, file_name, season_dir):
    # we need to strip out ads from the HLS manually
    playlist = m3u8.load(url)
    # filter out ad segments
    playlist.segments = m3u8.SegmentList(
        segment for segment in playlist.segments if "prd/creative/" not in segment.uri and not "_ad" in segment.uri
    )
    # write to a temporary file
    temp_playlist_path = working_dir / f"{file_name}.m3u8"
    with open(temp_playlist_path, "w") as f:
        f.write(playlist.dumps())
    # construct a file url
    file_url = f"file:///{temp_playlist_path.resolve()}"
    os.chdir(season_dir)
    ret_code = subprocess.Popen(
        [
            "yt-dlp",
            "--force-generic-extractor",
            "--enable-file-urls",
            "--downloader",
            "aria2c",
            "-o",
            f"{file_name}.%(ext)s",
            f"{file_url}",
        ]
    ).wait()
    if ret_code != 0:
        print("Return code from the downloader was non-0 (error), skipping!")
    else:
        print("Download Complete")
    os.chdir(home_dir)
    # remove the temporary playlist file
    if temp_playlist_path.exists():
        try:
            temp_playlist_path.unlink()
        except Exception as e:
            print(f"Error removing temporary playlist file: {e}")


def check_for_aria():
    try:
        subprocess.Popen(["aria2c", "-v"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).wait()
        return True
    except FileNotFoundError:
        return False
    except Exception as e:
        print("> Unexpected exception while checking for Aria2c, please tell the program author about this! ", e)
        return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pluto Downloader")
    parser.add_argument("-c", "--client-id", dest="client_id", type=str, help="client id", required=True)

    parser.add_argument("-i", "--item-id", dest="item_id", type=str, help="item id", required=True)

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

    pluto = Pluto(client_id=args.client_id, channel_id="5a66795ef91fef2c7031c599", item_id=args.item_id)

    authdata = pluto.fetch_authdata()
    pluto.set_authdata(authdata)

    item = pluto.fetch_items()
    item_type = item.get("type")

    if item_type == "series":
        print("Fetching series info...")
        details = pluto.fetch_seasons()
        series_name = details.get("name")
        slug = details.get("slug")
        series_dir = os.path.join(download_dir, slug)
        if not os.path.isdir(series_dir):
            os.mkdir(series_dir)

        seasons = details.get("seasons")
        print(f"Found {len(seasons)} seasons for series '{series_name}'")

        for season in seasons:
            season_number = season.get("number")
            season_dir = os.path.join(series_dir, f"S{season_number:02d}")
            if not os.path.isdir(season_dir):
                os.mkdir(season_dir)

            episodes = season.get("episodes")

            for episode in episodes:
                print(f"Processing episode {episode.get('name')} ({episodes.index(episode) + 1}/{len(episodes)})")
                episode_name = episode.get("name")
                episode_number = episode.get("number")
                episode_filename = sanitize(
                    f"{series_name}.S{season_number:02d}.E{episode_number:02d}.{episode_name}"
                ).replace(" ", ".")
                print(episode_filename)
                episode_path = os.path.join(season_dir, episode_filename)
                url_path = episode.get("stitched").get("path")
                url = pluto.make_stitcher_url(url_path)
                best_playlist_url = pluto.get_best_playlist_url(url)
                if not best_playlist_url:
                    print("No suitable best playlist found, skipping episode.")
                    continue
                download(best_playlist_url, episode_filename, season_dir)
                break
            break
    elif item_type == "movie":
        movie_name = item.get("name")
        if not os.path.isdir(download_dir):
            os.mkdir(download_dir)
        movie_filename = sanitize(movie_name).replace(" ", ".")
        movie_path = os.path.join(download_dir, movie_filename)
        url_path = item.get("stitched").get("path")
        url = pluto.make_stitcher_url(url_path)
        best_playlist_url = pluto.get_best_playlist_url(url)
        if not best_playlist_url:
            print("No suitable best playlist found")
        else:
            download(best_playlist_url, movie_filename, download_dir)
    else:
        print("Unknown item type, exiting...")
        sys.exit(1)
