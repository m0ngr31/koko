#!/usr/bin/python

# For a complete discussion, see http://forum.kodi.tv/showthread.php?tid=254502

import datetime
import random
import string
import time
import os
import re
import codecs
import logging
import music
from flask import Flask, json, render_template
from functools import wraps
from flask_ask import Ask, session, question, statement, audio, request, context
from shutil import copyfile

from kodi_voice import KodiConfigParser, Kodi


app = Flask(__name__)

config_file = os.path.join(os.path.dirname(__file__), "kodi.config")
config = KodiConfigParser(config_file)

LOGLEVEL = config.get('global', 'loglevel')
LOGSENSITIVE = config.getboolean('global', 'logsensitive')
logging.basicConfig(level=logging.INFO)
log = logging.getLogger('kodi_alexa.' + __name__)
log.setLevel(LOGLEVEL)
kodi_voice_log = logging.getLogger('kodi_voice')
kodi_voice_log.setLevel(LOGLEVEL)
kodi_voice_log.propagate = True
if LOGSENSITIVE:
  requests_log = logging.getLogger('requests.packages.urllib3')
  requests_log.setLevel(LOGLEVEL)
  requests_log.propagate = True

SKILL_ID = config.get('alexa', 'skill_id')
if SKILL_ID and SKILL_ID != 'None' and not os.getenv('MEDIA_CENTER_SKILL_ID'):
  app.config['ASK_APPLICATION_ID'] = SKILL_ID

LANGUAGE = config.get('global', 'language')
if LANGUAGE and LANGUAGE != 'None' and LANGUAGE == 'de':
  TEMPLATE_FILE = "templates.de.yaml"
else:
  LANGUAGE = 'en'
  TEMPLATE_FILE = "templates.en.yaml"

# According to this: https://alexatutorial.com/flask-ask/configuration.html
# Timestamp based verification shouldn't be used in production. Use at own risk
# app.config['ASK_VERIFY_TIMESTAMP_DEBUG'] = True

# Needs to be instanced after app is configured
ask = Ask(app, "/", None, path=TEMPLATE_FILE)


# Direct lambda handler
def lambda_handler(event, _context):
  return ask.run_aws_lambda(event)

# Decorator to check your config for basic info and if your account is linked (when using the hosted skill)
def preflight_check(f):
  @wraps(f)
  def decorated_function(*args, **kwargs):
    kodi = Kodi(config, context)

    if kodi.config_error:
      response_text = render_template('config_missing').encode('utf-8')

      card_title = render_template('card_config_missing').encode('utf-8')
      return statement(response_text).simple_card(card_title, response_text)

    CAN_STREAM = music.has_music_functionality(kodi)

    if not CAN_STREAM:
      response_text = render_template('config_missing').encode("utf-8")
      return statement(response_text)

    # Since we're not getting any of the actual args passed in, we have to create them here
    slots = request.get('intent', {}).get('slots', {})
    for key, value in slots.iteritems():
      kwargs.update({key: value.get('value')})
    kwargs.update({'kodi': kodi})

    return f(*args, **kwargs)
  return decorated_function


# Start of intent methods

# Handle the StreamArtist intent.
@ask.intent('StreamArtist')
@preflight_check
def alexa_stream_artist(kodi, Artist):
  heard_artist = str(Artist).lower().translate(None, string.punctuation)

  card_title = render_template('stream_artist', heard_artist=heard_artist).encode("utf-8")
  log.info(card_title)

  artists = kodi.GetMusicArtists()
  if 'result' in artists and 'artists' in artists['result']:
    artists_list = artists['result']['artists']
    located = kodi.matchHeard(heard_artist, artists_list, 'artist')

    if located:
      songs_result = kodi.GetArtistSongsPath(located['artistid'])
      songs = songs_result['result']['songs']

      songs_array = []

      for song in songs:
        songs_array.append(kodi.PrepareDownload(song['file']))

      if len(songs_array) > 0:
        random.shuffle(songs_array)
        playlist_queue = music.MusicPlayer(kodi, songs_array)

        response_text = render_template('streaming', heard_name=heard_artist).encode("utf-8")
        audio('').clear_queue(stop=True)
        return audio(response_text).play(songs_array[0])
      else:
        response_text = render_template('could_not_find', heard_name=heard_artist).encode("utf-8")
    else:
      response_text = render_template('could_not_find', heard_name=heard_artist).encode("utf-8")
  else:
    response_text = render_template('could_not_find', heard_name=heard_artist).encode("utf-8")

  return statement(response_text).simple_card(card_title, response_text)


# Handle the StreamAlbum intent (Stream whole album, or whole album by a specific artist).
@ask.intent('StreamAlbum')
@preflight_check
def alexa_stream_album(kodi, Album, Artist):
  heard_album = str(Album).lower().translate(None, string.punctuation)
  card_title = render_template('streaming_album_card').encode("utf-8")
  log.info(card_title)

  if Artist:
    heard_artist = str(Artist).lower().translate(None, string.punctuation)
    artists = kodi.GetMusicArtists()
    if 'result' in artists and 'artists' in artists['result']:
      artists_list = artists['result']['artists']
      located = kodi.matchHeard(heard_artist, artists_list, 'artist')

      if located:
        albums = kodi.GetArtistAlbums(located['artistid'])
        if 'result' in albums and 'albums' in albums['result']:
          albums_list = albums['result']['albums']
          album_located = kodi.matchHeard(heard_album, albums_list)

          if album_located:
            songs_result = kodi.GetAlbumSongsPath(album_located['albumid'])
            songs = songs_result['result']['songs']

            songs_array = []

            for song in songs:
              songs_array.append(kodi.PrepareDownload(song['file']))

            if len(songs_array) > 0:
              random.shuffle(songs_array)
              playlist_queue = music.MusicPlayer(kodi, songs_array)

              response_text = render_template('streaming_album_artist', album_name=heard_album, artist=heard_artist).encode("utf-8")
              audio('').clear_queue(stop=True)
              return audio(response_text).play(songs_array[0])
            else:
              response_text = render_template('could_not_find_album_artist', album_name=heard_album, artist=heard_artist).encode("utf-8")
          else:
            response_text = render_template('could_not_find_album_artist', album_name=heard_album, artist=heard_artist).encode("utf-8")
        else:
          response_text = render_template('could_not_find_album_artist', album_name=heard_album, artist=heard_artist).encode("utf-8")
      else:
        response_text = render_template('could_not_find_album_artist', album_name=heard_album, artist=heard_artist).encode("utf-8")
    else:
      response_text = render_template('could_not_find_album_artist', album_name=heard_album, artist=heard_artist).encode("utf-8")
  else:
    albums = kodi.GetAlbums()
    if 'result' in albums and 'albums' in albums['result']:
      albums_list = albums['result']['albums']
      album_located = kodi.matchHeard(heard_album, albums_list)

      if album_located:
        songs_result = kodi.GetAlbumSongsPath(album_located['albumid'])
        songs = songs_result['result']['songs']

        songs_array = []

        for song in songs:
          songs_array.append(kodi.PrepareDownload(song['file']))

        if len(songs_array) > 0:
          random.shuffle(songs_array)
          playlist_queue = music.MusicPlayer(kodi, songs_array)

          response_text = render_template('streaming_album', album_name=heard_album).encode("utf-8")
          audio('').clear_queue(stop=True)
          return audio(response_text).play(songs_array[0])
        else:
          response_text = render_template('could_not_find_album', album_name=heard_album).encode("utf-8")
      else:
        response_text = render_template('could_not_find_album', album_name=heard_album).encode("utf-8")
    else:
      response_text = render_template('could_not_find_album', album_name=heard_album).encode("utf-8")

  return statement(response_text).simple_card(card_title, response_text)


# Handle the StreamSong intent (Stream a song, or song by a specific artist).
@ask.intent('StreamSong')
@preflight_check
def alexa_stream_song(kodi, Song, Artist):
  heard_song = str(Song).lower().translate(None, string.punctuation)
  card_title = render_template('streaming_song_card').encode("utf-8")
  log.info(card_title)

  if Artist:
    heard_artist = str(Artist).lower().translate(None, string.punctuation)
    artists = kodi.GetMusicArtists()
    if 'result' in artists and 'artists' in artists['result']:
      artists_list = artists['result']['artists']
      located = kodi.matchHeard(heard_artist, artists_list, 'artist')

      if located:
        songs = kodi.GetArtistSongs(located['artistid'])
        if 'result' in songs and 'songs' in songs['result']:
          songs_list = songs['result']['songs']
          song_located = kodi.matchHeard(heard_song, songs_list)

          if song_located:
            songs_array = []
            song = None

            song_result = kodi.GetSongIdPath(song_located['songid'])

            if 'songdetails' in song_result['result']:
              song = song_result['result']['songdetails']['file']

            if song:
              songs_array.append(kodi.PrepareDownload(song))

            if len(songs_array) > 0:
              random.shuffle(songs_array)
              playlist_queue = music.MusicPlayer(kodi, songs_array)

              response_text = render_template('streaming_song_artist', song_name=heard_song, artist=heard_artist).encode("utf-8")
              audio('').clear_queue(stop=True)
              return audio(response_text).play(songs_array[0])
            else:
              response_text = render_template('could_not_find_song_artist', song_name=heard_song, artist=heard_artist).encode("utf-8")
          else:
            response_text = render_template('could_not_find_song_artist', song_name=heard_song, artist=heard_artist).encode("utf-8")
        else:
          response_text = render_template('could_not_find_song_artist', song_name=heard_song, artist=heard_artist).encode("utf-8")
      else:
        response_text = render_template('could_not_find_song_artist', song_name=heard_song, artist=heard_artist).encode("utf-8")
    else:
      response_text = render_template('could_not_find_song_artist', song_name=heard_song, artist=heard_artist).encode("utf-8")
  else:
    songs = kodi.GetSongs()
    if 'result' in songs and 'songs' in songs['result']:
      songs_list = songs['result']['songs']
      song_located = kodi.matchHeard(heard_song, songs_list)

      if song_located:
        songs_array = []
        song = None

        song_result = kodi.GetSongIdPath(song_located['songid'])

        if 'songdetails' in song_result['result']:
          song = song_result['result']['songdetails']['file']

        if song:
          songs_array.append(kodi.PrepareDownload(song))

        if len(songs_array) > 0:
          random.shuffle(songs_array)
          playlist_queue = music.MusicPlayer(kodi, songs_array)

          response_text = render_template('streaming_song', song_name=heard_song).encode("utf-8")
          audio('').clear_queue(stop=True)
          return audio(response_text).play(songs_array[0])
        else:
          response_text = render_template('could_not_find_song', song_name=heard_song).encode("utf-8")
      else:
        response_text = render_template('could_not_find_song', song_name=heard_song).encode("utf-8")
    else:
      response_text = render_template('could_not_find_song', song_name=heard_song).encode("utf-8")

  return statement(response_text).simple_card(card_title, response_text)


# Handle the StreamAlbumOrSong intent (Stream whole album or song by a specific artist).
@ask.intent('StreamAlbumOrSong')
@preflight_check
def alexa_stream_album_or_song(kodi, Song, Album, Artist):
  if Song:
    heard_search = str(Song).lower().translate(None, string.punctuation)
  elif Album:
    heard_search = str(Album).lower().translate(None, string.punctuation)
  if Artist:
    heard_artist = str(Artist).lower().translate(None, string.punctuation)

  card_title = render_template('streaming_album_or_song').encode("utf-8")
  log.info(card_title)

  artists = kodi.GetMusicArtists()
  if 'result' in artists and 'artists' in artists['result']:
    artists_list = artists['result']['artists']
    located = kodi.matchHeard(heard_artist, artists_list, 'artist')

    if located:
      albums = kodi.GetArtistAlbums(located['artistid'])
      if 'result' in albums and 'albums' in albums['result']:
        albums_list = albums['result']['albums']
        album_located = kodi.matchHeard(heard_search, albums_list)

        if album_located:
          songs_result = kodi.GetAlbumSongsPath(album_located['albumid'])
          songs = songs_result['result']['songs']

          songs_array = []

          for song in songs:
            songs_array.append(kodi.PrepareDownload(song['file']))

          if len(songs_array) > 0:
            random.shuffle(songs_array)
            playlist_queue = music.MusicPlayer(kodi, songs_array)

            response_text = render_template('streaming_album_artist', album_name=heard_search, artist=heard_artist).encode("utf-8")
            audio('').clear_queue(stop=True)
            return audio(response_text).play(songs_array[0])
          else:
            response_text = render_template('could_not_find_album_artist', album_name=heard_search, artist=heard_artist).encode("utf-8")
        else:
          songs = kodi.GetArtistSongs(located['artistid'])
          if 'result' in songs and 'songs' in songs['result']:
            songs_list = songs['result']['songs']
            song_located = kodi.matchHeard(heard_search, songs_list)

            if song_located:
              songs_array = []
              song = None

              song_result = kodi.GetSongIdPath(song_located['songid'])

              if 'songdetails' in song_result['result']:
                song = song_result['result']['songdetails']['file']

              if song:
                songs_array.append(kodi.PrepareDownload(song))

              if len(songs_array) > 0:
                random.shuffle(songs_array)
                playlist_queue = music.MusicPlayer(kodi, songs_array)

                response_text = render_template('streaming_song_artist', song_name=heard_search, artist=heard_artist).encode("utf-8")
                audio('').clear_queue(stop=True)
                return audio(response_text).play(songs_array[0])
              else:
                response_text = render_template('could_not_find_song_artist', song_name=heard_search, artist=heard_artist).encode("utf-8")
            else:
              response_text = render_template('could_not_find_song_artist', heard_name=heard_search, artist=heard_artist).encode("utf-8")
          else:
            response_text = render_template('could_not_find_song_artist', heard_name=heard_search, artist=heard_artist).encode("utf-8")
      else:
        response_text = render_template('could_not_find_song_artist', heard_name=heard_search, artist=heard_artist).encode("utf-8")
    else:
      response_text = render_template('could_not_find_song_artist', heard_name=heard_search, artist=heard_artist).encode("utf-8")
  else:
    response_text = render_template('could_not_find', heard_name=heard_artist).encode("utf-8")

  return statement(response_text).simple_card(card_title, response_text)


# Handle the StreamAudioPlaylistRecent intent (Shuffle and stream all recently added songs).
@ask.intent('StreamAudioPlaylistRecent')
@preflight_check
def alexa_stream_recently_added_songs(kodi):
  card_title = render_template('streaming_recent_songs').encode("utf-8")
  response_text = render_template('no_recent_songs').encode("utf-8")
  log.info(card_title)

  songs_result = kodi.GetRecentlyAddedSongsPath()
  if songs_result:
    songs = songs_result['result']['songs']

    songs_array = []

    for song in songs:
      songs_array.append(kodi.PrepareDownload(song['file']))

    if len(songs_array) > 0:
      random.shuffle(songs_array)
      playlist_queue = music.MusicPlayer(kodi, songs_array)

      response_text = render_template('streaming_recent_songs').encode("utf-8")
      audio('').clear_queue(stop=True)
      return audio(response_text).play(songs_array[0])

  return statement(response_text).simple_card(card_title, response_text)


# Handle the StreamAudioPlaylist intent.
@ask.intent('StreamAudioPlaylist')
@preflight_check
def alexa_stream_audio_playlist(kodi, AudioPlaylist, shuffle=False):
  heard_search = str(AudioPlaylist).lower().translate(None, string.punctuation)

  if shuffle:
    op = render_template('shuffling_empty').encode("utf-8")
  else:
    op = render_template('playing').encode("utf-8")

  card_title = render_template('action_audio_playlist', action=op).encode("utf-8")
  log.info(card_title)

  playlist = kodi.FindAudioPlaylist(heard_search)
  if playlist:
    songs = kodi.GetPlaylistItems(playlist)['result']['files']

    songs_array = []

    for song in songs:
      songs_array.append(kodi.PrepareDownload(song['file']))

    if len(songs_array) > 0:
      if shuffle:
        random.shuffle(songs_array)
      playlist_queue = music.MusicPlayer(kodi, songs_array)

      response_text = render_template('playing_playlist', action=op, playlist_name=heard_search).encode("utf-8")
      audio('').clear_queue(stop=True)
      return audio(response_text).play(songs_array[0])
    else:
      response_text = render_template('could_not_find_playlist', heard_name=heard_search).encode("utf-8")
  else:
    response_text = render_template('could_not_find_playlist', heard_name=heard_search).encode("utf-8")

  return statement(response_text).simple_card(card_title, response_text)


# Handle the StreamPartyMode intent.
@ask.intent('StreamPartyMode')
@preflight_check
def alexa_stream_party_play(kodi):
  card_title = render_template('streaming_party_mode').encode("utf-8")
  log.info(card_title)

  response_text = render_template('streaming_party').encode("utf-8")

  songs = kodi.GetSongsPath()

  if 'result' in songs and 'songs' in songs['result']:
    songs_array = []

    for song in songs['result']['songs']:
      songs_array.append(kodi.PrepareDownload(song['file']))

    if len(songs_array) > 0:
      random.shuffle(songs_array)
      playlist_queue = music.MusicPlayer(kodi, songs_array)

      response_text = render_template('streaming_party').encode("utf-8")
      audio('').clear_queue(stop=True)
      return audio(response_text).play(songs_array[0])
    else:
      response_text = render_template('error_parsing_results').encode("utf-8")
  else:
    response_text = render_template('error_parsing_results').encode("utf-8")

  return statement(response_text).simple_card(card_title, response_text)



# Handle the SteamThis intent.
@ask.intent('StreamThis')
@preflight_check
def alexa_stream_this(kodi):
  card_title = render_template('streaming_current_playlist').encode("utf-8")
  log.info(card_title)

  current_item = kodi.GetActivePlayItem()

  if current_item and current_item['type'] == 'song':
    play_status = kodi.GetPlayerStatus()
    playlist_items = []
    final_playlist = []
    songs_array = []

    offset = 0
    current_time = play_status['time']
    if len(current_time) == 5:
      x = time.strptime(current_time, '%M:%S')
    else:
      x = time.strptime(current_time, '%H:%M:%S')
    offset = int(datetime.timedelta(hours=x.tm_hour,
                                    minutes=x.tm_min, seconds=x.tm_sec).total_seconds()) * 1000

    playlist_result = kodi.GetAudioPlaylistItems()

    if 'items' in playlist_result['result']:
      playlist_items = playlist_result['result']['items']

    if len(playlist_items) > 0:
      current_playing = next(
          (x for x in playlist_items if x['id'] == current_item['id']), None)
      current_index = playlist_items.index(current_playing)
      final_playlist = playlist_items[current_index:]

    if len(final_playlist) > 0:
      for song in final_playlist:
        song_detail = kodi.GetSongIdPath(song['id'])
        song_detail = song_detail['result']['songdetails']
        songs_array.append(kodi.PrepareDownload(song_detail['file']))

    if len(songs_array) > 0:
      playlist_queue = music.MusicPlayer(kodi, songs_array)

      kodi.Stop()
      kodi.ClearAudioPlaylist()

      response_text = render_template('transferring_stream').encode("utf-8")
      audio('').clear_queue(stop=True)
      return audio(response_text).play(songs_array[0])

  else:
    response_text = render_template('nothing_currently_playing')

  return statement(response_text).simple_card(card_title, response_text)


@ask.intent('AMAZON.PauseIntent')
@preflight_check
def alexa_stream_pause(kodi):
  audio('').clear_queue()
  return audio('').stop()


# NextIntent steps queue forward and clears enqueued streams that were already sent to Alexa
# next_stream will match queue.up_next and enqueue Alexa with the correct subsequent stream.
@ask.intent('AMAZON.NextIntent')
@preflight_check
def alexa_stream_skip(kodi):
  playlist_queue = music.MusicPlayer(kodi)

  if playlist_queue.next_item:
    playlist_queue.skip_song()
    # current_item is now set as the next item from the playlist
    return audio('').play(playlist_queue.current_item)
  else:
    response_text = render_template('no_more_songs').encode("utf-8")
    return audio(response_text)


@ask.intent('AMAZON.PreviousIntent')
@preflight_check
def alexa_stream_prev(kodi):
  playlist_queue = music.MusicPlayer(kodi)

  if playlist_queue.prev_item:
    playlist_queue.prev_song()
    # current_item is now set as the previous item from the playlist
    return audio('').play(playlist_queue.current_item)
  else:
    response_text = render_template('no_songs_history').encode("utf-8")
    return audio(response_text)


@ask.intent('AMAZON.StartOverIntent')
@preflight_check
def alexa_stream_restart_track(kodi):
  playlist_queue = music.MusicPlayer(kodi)

  if playlist_queue.current_item:
    return audio('').play(playlist_queue.current_item, offset=0)
  else:
    response_text = render_template('no_current_song').encode("utf-8")
    return audio(response_text)


@ask.intent('AMAZON.ResumeIntent')
@preflight_check
def alexa_stream_resume(kodi):
  return audio('').resume()


# Handle the AMAZON.LoopOnIntent intent.
# @ask.intent('AMAZON.LoopOnIntent')
# @preflight_check
# def alexa_loop_on(kodi):
#   card_title = render_template('loop_enable').encode('utf-8')
#   log.info(card_title)

#   kodi.PlayerLoopOn()

#   response_text = ''

#   curprops = kodi.GetActivePlayProperties()
#   if curprops is not None:
#     if curprops['repeat'] == 'one':
#       response_text = render_template('loop_one').encode('utf-8')
#     elif curprops['repeat'] == 'all':
#       response_text = render_template('loop_all').encode('utf-8')
#     elif curprops['repeat'] == 'off':
#       response_text = render_template('loop_off').encode('utf-8')

#   return statement(response_text).simple_card(card_title, response_text)


# Handle the AMAZON.LoopOffIntent intent.
# @ask.intent('AMAZON.LoopOffIntent')
# @preflight_check
# def alexa_loop_off(kodi):
#   card_title = render_template('loop_disable').encode('utf-8')
#   log.info(card_title)

#   kodi.PlayerLoopOff()
#   response_text = render_template('loop_off').encode('utf-8')
#   return statement(response_text).simple_card(card_title, response_text)



# This allows for Next Intents and on_playback_finished requests to trigger the step
@ask.on_playback_nearly_finished()
def nearly_finished():
  kodi = Kodi(config, context)
  playlist_queue = music.MusicPlayer(kodi)

  if playlist_queue.next_item:
    return audio().enqueue(playlist_queue.next_item)


@ask.on_playback_finished()
def play_back_finished():
  kodi = Kodi(config, context)
  playlist_queue = music.MusicPlayer(kodi)

  if playlist_queue.next_item:
    playlist_queue.skip_song()


@ask.on_playback_started()
def started(offset):
  log.info('Streaming started')


@ask.on_playback_stopped()
def stopped(offset):
  kodi = Kodi(config, context)
  playlist_queue = music.MusicPlayer(kodi)

  playlist_queue.current_offset = offset
  playlist_queue.save_to_mongo()
  audio().enqueue(playlist_queue.current_item)
  log.info('Streaming stopped')


def get_help_samples(limit=7):
  # read example slot values from language-specific file.
  sample_slotvals = {}
  fn = os.path.join(os.path.dirname(__file__), 'sample_slotvals.%s.txt' % (LANGUAGE))
  f = codecs.open(fn, 'rb', 'utf-8')
  for line in f:
    media_type, media_title = line.encode('utf-8').strip().split(' ', 1)
    sample_slotvals[media_type] = media_title.strip()
  f.close()

  # don't suggest utterances for the following intents, because they depend on
  # context to make any sense:
  ignore_intents = []

  # build complete list of possible utterances from file.
  utterances = {}
  fn = os.path.join(os.path.dirname(__file__), 'speech_assets/SampleUtterances.%s.txt' % (LANGUAGE))
  f = codecs.open(fn, 'rb', 'utf-8')
  for line in f:
    intent, utterance = line.encode('utf-8').strip().split(' ', 1)
    if intent in ignore_intents: continue
    if intent not in utterances:
      utterances[intent] = []
    utterances[intent].append(utterance)
  f.close()

  # pick random utterances to return, up to the specified limit.
  sample_utterances = {}
  for k in random.sample(utterances.keys(), limit):
    # substitute slot references for sample media titles.
    sample_utterances[k] = re.sub(r'{(\w+)?}', lambda m: sample_slotvals.get(m.group(1), m.group(1)), random.choice(utterances[k])).decode('utf-8')

  return sample_utterances


@ask.intent('AMAZON.HelpIntent')
@preflight_check
def prepare_help_message(kodi):
  sample_utterances = get_help_samples()

  response_text = render_template('help', example=sample_utterances.popitem()[1]).encode('utf-8')
  reprompt_text = render_template('help_short', example=sample_utterances.popitem()[1]).encode('utf-8')
  card_title = render_template('help_card').encode('utf-8')
  samples = ''
  for sample in sample_utterances.values():
    samples += '"%s"\n' % (sample)
  card_text = render_template('help_text', examples=samples).encode('utf-8')
  log.info(card_title)

  if not 'queries_keep_open' in session.attributes:
    return statement(response_text).simple_card(card_title, card_text)

  return question(response_text).reprompt(reprompt_text).simple_card(card_title, card_text)


# No intents invoked
@ask.launch
def alexa_launch():
  sample_utterances = get_help_samples()

  response_text = render_template('welcome').encode('utf-8')
  reprompt_text = render_template('help_short', example=sample_utterances.popitem()[1]).encode('utf-8')
  card_title = response_text
  log.info(card_title)

  # All non-playback requests should keep the session open
  session.attributes['queries_keep_open'] = True

  return question(response_text).reprompt(reprompt_text)


@ask.session_ended
def session_ended():
  return "{}", 200


# End of intent methods
