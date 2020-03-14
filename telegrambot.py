#!/usr/bin/python3

import os, sys, time, random
import apsw
import urllib.request as url
import urllib.parse as urlparse
from urllib.error import URLError
from time import sleep
from threading import Thread, Lock, current_thread, Event
from signal import signal, SIGINT, SIGTERM, SIGABRT
from botman import SettingGroup, BotmanCore, BotmanInterface
import json
import unicodedata

DBFILENAME='tbotman.sqlite'
BASE_URL='https://api.telegram.org/bot'
MAX_SENTENCE = 320

class TelegramBotman(BotmanInterface):
	def __init__(self):
		super().__init__()
		if self.running:
			self.run()
			self.apikey = self.settings['telegram_apikey']
			me = self.getJsonResponse('getMe')
			nick = me['result']['first_name'].lower()
			if not nick in self.aliases:
				self.aliases.append(nick)
	def start(self):
		while self.running:
			self.update()
	def getJsonResponse(self, method, **kwargs):
		parameters = []
		for key, value in kwargs.items():
			parameters.append((str(key), str(value)))
		urlparams = urlparse.urlencode(parameters).encode('UTF-8')
		final_url = '%s%s/%s' % (BASE_URL, self.apikey, method)
		try:
			return json.loads(url.urlopen(final_url, urlparams).read().decode('UTF-8'))
		except URLError as err:
			print('URL error:', err)
			return
	def update(self):
		updates = self.getJsonResponse('getUpdates', offset=int(self.settings['telegram_lastUpdate']))
		lastUpdate = None
		if updates:
			for update in updates['result']:
				self.process_update(update)
				lastUpdate = update['update_id']
			if lastUpdate:
				self.settings['telegram_lastUpdate'] = lastUpdate + 1
		sleep(1)
	def process_update(self, update):
		if 'message' in update:
			if 'text' in update['message']:
				message = update['message']['text']
				chat_id = int(update['message']['chat']['id'])
				message_id = int(update['message']['message_id'])
				self.receivemessage(message, chat_id, {'original_id': message_id})
	def sendnewsentence(self, chat_id, base = '', invert = False, read_result = None, userparams = None):
		sentence = self.corebot.sendnewsentence(chat_id, base, invert, read_result, userparams)
		if 'original_id' in userparams and self.counter[chat_id] > 0:
			self.getJsonResponse('sendMessage', chat_id=chat_id, text=sentence, reply_to_message_id=userparams['original_id'])
		else:
			self.getJsonResponse('sendMessage', chat_id=chat_id, text=sentence)
	def configure(self):
		super().configure()
		apikey = input('API key (empty = unchanged): ').strip()
		if len(apikey) > 0:
			self.settings['telegram_apikey'] = apikey
		self.settings['telegram_lastUpdate'] = 0

def display_help():
	print('Usage: ./botman.py [optional command]')
	print('List of special commands:')
	print('* help to print this help')
	print('* init to initialize the database and configuration then launch the bot for the first time')
	print('* config to only change the configuration of the bot, such as IRC settings')
	print('* feed [filename] to feed a text file to the database')

def feed_db(filenames):
	connection=apsw.Connection(DBFILENAME)
	botman = Botman(SettingGroup(connection), connection)
	slist = []
	for filename in filenames:
		with open(filename, 'r', encoding='utf-8') as infile:
			for line in infile:
				if len(line) > 0:
					slist.append(line.replace("\r", "").replace("\n", "").replace("\t", " "))
	for sentence in slist:
		botman.readstring(sentence)
	connection.close()

TelegramBotman().start()
